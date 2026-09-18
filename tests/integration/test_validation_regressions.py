"""Regression coverage for validation session lifecycle defects.

Each test here pins behaviour that was wrong in the original validation
workflow commit: parked sessions being garbage collected by the lease sweep,
a scope change locking the validator out of the field that caused it,
reprocessing writing back a stale session snapshot, and a section update
silently erasing extracted data.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.incidents import IncidentReport
from app.models.sources import ArticleScopeClassification, Source
from app.models.task import TaskStatus
from app.models.validation import ValidationSession
from app.service.validation_service import ValidationService


async def _session(
    source_id: str,
    validator_id: str,
    status: str = "IN_PROGRESS",
    expired: bool = False,
) -> ValidationSession:
    offset = timedelta(minutes=-1 if expired else 15)
    session = ValidationSession(
        source_id=source_id,
        validator_id=validator_id,
        status=status,
        lock_expires_at=datetime.now(timezone.utc) + offset,
        flag_reason="Needs administrator attention" if status == "FLAGGED" else None,
    )
    await session.insert()
    return session


async def _active_session(source_id: str) -> ValidationSession | None:
    return await ValidationSession.find_one(
        {"source_id": source_id, "status": {"$ne": "RELEASED"}}
    )


# --------------------------------------------------------------------------
# Lease expiry: sessions parked on somebody else must not be swept away.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["FLAGGED", "REPROCESSING_REQUIRED"])
async def test_parked_sessions_survive_lock_expiry(
    test_db, sample_source, validator_user, status
):
    """A session waiting on an admin or on a background job is not idle.

    Expiring it loses the flag (the admin can no longer resolve it) or lets a
    second validator lease a source that reprocessing is about to write to.
    """
    session = await _session(
        str(sample_source.id), str(validator_user.id), status, expired=True
    )

    await ValidationService._expire_stale_sessions()

    refreshed = await ValidationSession.get(session.id)
    assert refreshed.status == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["IN_PROGRESS", "READY_FOR_REVALIDATION", "SCOPE_CHANGED"]
)
async def test_idle_validator_leases_still_expire(
    test_db, sample_source, validator_user, status
):
    """The sweep must still reclaim sources from validators who walked away."""
    session = await _session(
        str(sample_source.id), str(validator_user.id), status, expired=True
    )

    await ValidationService._expire_stale_sessions()

    refreshed = await ValidationSession.get(session.id)
    assert refreshed.status == "RELEASED"


@pytest.mark.asyncio
async def test_flagged_session_is_still_resolvable_after_lock_expiry(
    test_db, sample_source, validator_user
):
    """End-to-end version of the above: the admin queue still works."""
    session = await _session(
        str(sample_source.id), str(validator_user.id), "FLAGGED", expired=True
    )

    # Any admin read runs the sweep; it must not destroy the flag.
    listing = await ValidationService.admin_sessions(view="flagged")
    assert listing["pagination"]["total"] == 1

    resolved = await ValidationService.admin_resolve_flag(str(session.id), "resume")
    assert resolved["status"] == "IN_PROGRESS"


# --------------------------------------------------------------------------
# Scope change: must not lock the validator out of Tier A.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_change_leaves_tier_a_editable(
    test_db, sample_source, validator_user
):
    """A mis-picked scope has to be correctable without a destructive reprocess."""
    await ValidationService.start(str(sample_source.id), validator_user)

    source = await Source.get(sample_source.id)
    await ValidationService.update_tier_a(
        str(sample_source.id),
        validator_user,
        source.version,
        ArticleScopeClassification(articleType="Industry Overview", confidence=1),
        True,
        {},
    )

    session = await _active_session(str(sample_source.id))
    assert session.status == "SCOPE_CHANGED"
    assert session.task_id is None

    # The whole point: the validator can put the scope back.
    source = await Source.get(sample_source.id)
    workspace = await ValidationService.update_tier_a(
        str(sample_source.id),
        validator_user,
        source.version,
        ArticleScopeClassification(articleType="Single Incident", confidence=1),
        True,
        {},
    )
    assert workspace["source"]["article_scope"]["articleType"] == "Single Incident"


@pytest.mark.asyncio
async def test_scope_change_still_allows_flagging(
    test_db, sample_source, validator_user
):
    """A validator who is unsure after a scope change can still ask for help."""
    await ValidationService.start(str(sample_source.id), validator_user)
    source = await Source.get(sample_source.id)
    await ValidationService.update_tier_a(
        str(sample_source.id),
        validator_user,
        source.version,
        ArticleScopeClassification(articleType="Industry Overview", confidence=1),
        True,
        {},
    )

    flagged = await ValidationService.flag(
        str(sample_source.id), validator_user, "Scope is ambiguous"
    )
    assert flagged["status"] == "FLAGGED"


@pytest.mark.asyncio
async def test_reprocessing_in_flight_still_blocks_edits(
    test_db, sample_source, validator_user
):
    """SCOPE_CHANGED is editable, but a running reprocess must stay locked."""
    await _session(
        str(sample_source.id), str(validator_user.id), "REPROCESSING_REQUIRED"
    )

    source = await Source.get(sample_source.id)
    with pytest.raises(Exception) as exc:
        await ValidationService.update_tier_a(
            str(sample_source.id),
            validator_user,
            source.version,
            ArticleScopeClassification(articleType="Single Incident", confidence=1),
            True,
            {},
        )
    assert getattr(exc.value, "status_code", None) == 409


# --------------------------------------------------------------------------
# Reprocessing: the long-running job must not write back a stale snapshot.
# --------------------------------------------------------------------------


async def _reprocessing_fixtures(source, validator):
    task = TaskStatus(
        task_type="validation_reprocessing",
        user_id=str(validator.id),
        input_params={"source_id": str(source.id)},
    )
    await task.insert()
    session = await _session(str(source.id), str(validator.id), "REPROCESSING_REQUIRED")
    session.task_id = task.task_id
    await session.save()
    return session, task


@pytest.mark.asyncio
async def test_run_reprocessing_does_not_resurrect_a_released_session(
    test_db, sample_source, validator_user
):
    """The validator releases the lease while the LLM is still running.

    The re-analysis must not flip the session back to an active status: doing
    so revives a lease the validator gave up, and can collide with the partial
    unique index if somebody else has since leased the source.
    """
    session, task = await _reprocessing_fixtures(sample_source, validator_user)

    async def _reclassify(source, scope):
        live = await ValidationSession.get(session.id)
        live.status = "RELEASED"
        live.lock_expires_at = datetime.now(timezone.utc)
        await live.save()
        return source

    with patch(
        "app.service.source_service.SourceService._reclassify_source",
        side_effect=_reclassify,
    ):
        await ValidationService.run_reprocessing(
            str(session.id),
            str(sample_source.id),
            "Single Incident",
            task.task_id,
            str(validator_user.id),
        )

    refreshed = await ValidationSession.get(session.id)
    assert refreshed.status == "RELEASED"


@pytest.mark.asyncio
async def test_run_reprocessing_does_not_clobber_concurrent_section_review(
    test_db, sample_source, validator_user
):
    """Writes made during the re-analysis window must survive it.

    `validator_id` stands in for any field reprocessing does not own: an admin
    handing the session to someone else mid-analysis must not be undone by the
    write-back.
    """
    session, task = await _reprocessing_fixtures(sample_source, validator_user)

    async def _reclassify(source, scope):
        live = await ValidationSession.get(session.id)
        live.validator_id = "reassigned-validator"
        await live.save()
        return source

    with patch(
        "app.service.source_service.SourceService._reclassify_source",
        side_effect=_reclassify,
    ):
        await ValidationService.run_reprocessing(
            str(session.id),
            str(sample_source.id),
            "Single Incident",
            task.task_id,
            str(validator_user.id),
        )

    refreshed = await ValidationSession.get(session.id)
    assert refreshed.validator_id == "reassigned-validator"


@pytest.mark.asyncio
async def test_run_reprocessing_failure_handler_never_escapes(
    test_db, sample_source, validator_user
):
    """A failing recovery write must not leave the task un-failed.

    The original handler called the same save() that had just failed, so the
    second exception escaped the BackgroundTask and wedged the session.
    """
    session, task = await _reprocessing_fixtures(sample_source, validator_user)

    async def _boom(source, scope):
        raise RuntimeError("analysis exploded")

    with patch(
        "app.service.source_service.SourceService._reclassify_source",
        side_effect=_boom,
    ):
        with patch.object(
            ValidationSession, "save", side_effect=RuntimeError("mongo unavailable")
        ):
            await ValidationService.run_reprocessing(
                str(session.id),
                str(sample_source.id),
                "Single Incident",
                task.task_id,
                str(validator_user.id),
            )

    refreshed_task = await TaskStatus.find_one(TaskStatus.task_id == task.task_id)
    assert refreshed_task.status == "failed"


# --------------------------------------------------------------------------
# Section updates: omitting `value` must not erase the section.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_update_without_value_preserves_existing_data(
    test_db, sample_source, sample_incident, validator_user
):
    """Ticking the review box must not blank the section it reviews."""
    await ValidationService.start(str(sample_source.id), validator_user)
    incident = await IncidentReport.get(sample_incident.id)

    await ValidationService.update_section(
        str(incident.id),
        "vesselInformation",
        validator_user,
        incident.version,
        value=None,
        reviewed=True,
        value_provided=False,
    )

    refreshed = await IncidentReport.get(sample_incident.id)
    assert refreshed.extracted_information.vesselInformation is not None
    assert refreshed.extracted_information.vesselInformation.vesselName == "Test Vessel"

    session = await _active_session(str(sample_source.id))
    assert "vesselInformation" in session.reviewed_sections[str(incident.id)]


@pytest.mark.asyncio
async def test_section_update_with_explicit_null_still_clears_the_section(
    test_db, sample_source, sample_incident, validator_user
):
    """Deliberately sending null remains a way to empty a section."""
    await ValidationService.start(str(sample_source.id), validator_user)
    incident = await IncidentReport.get(sample_incident.id)

    await ValidationService.update_section(
        str(incident.id),
        "vesselInformation",
        validator_user,
        incident.version,
        value=None,
        reviewed=True,
        value_provided=True,
    )

    refreshed = await IncidentReport.get(sample_incident.id)
    assert refreshed.extracted_information.vesselInformation is None
