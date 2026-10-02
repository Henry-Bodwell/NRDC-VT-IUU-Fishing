from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.audit.context import AuditContext
from app.models.sources import ArticleScopeClassification
from app.models.users import User
from app.models.validation import ValidationSession
from app.service.validation_service import ValidationService
from tests.conftest import (
    make_incident,
    make_overview,
    make_overview_extract,
    make_source,
)


@pytest.mark.asyncio
async def test_only_one_validator_can_hold_a_source_lease(
    test_db, sample_source, validator_user
):
    second = User(
        email="second-validator@example.com",
        hashedPassword="unused",
        role="validator",
        can_validate=True,
    )
    await second.insert()

    with AuditContext.with_user(str(validator_user.id)):
        workspace = await ValidationService.start(
            str(sample_source.id), validator_user
        )
    assert workspace["session"]["validator_id"] == str(validator_user.id)

    with pytest.raises(HTTPException) as exc:
        with AuditContext.with_user(str(second.id)):
            await ValidationService.start(str(sample_source.id), second)
    assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_expired_lease_is_released_before_reassignment(
    test_db, sample_source, validator_user
):
    expired = ValidationSession(
        source_id=str(sample_source.id),
        validator_id="former-validator",
        lock_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    await expired.insert()

    with AuditContext.with_user(str(validator_user.id)):
        workspace = await ValidationService.start(
            str(sample_source.id), validator_user
        )

    refreshed_expired = await ValidationSession.get(expired.id)
    assert refreshed_expired.status == "RELEASED"
    assert workspace["session"]["validator_id"] == str(validator_user.id)


@pytest.mark.asyncio
async def test_worklist_returns_total_and_server_side_pages(
    test_db, sample_source, validator_user
):
    await make_source(article_title="Second source").insert()
    await make_source(article_title="Third source").insert()

    first_page = await ValidationService.worklist(
        validator_user, view="available", skip=0, limit=2
    )
    second_page = await ValidationService.worklist(
        validator_user, view="available", skip=2, limit=2
    )

    assert first_page["pagination"] == {
        "total": 3,
        "skip": 0,
        "limit": 2,
        "has_more": True,
    }
    assert len(first_page["items"]) == 2
    assert second_page["pagination"]["total"] == 3
    assert len(second_page["items"]) == 1


@pytest.mark.asyncio
async def test_flagged_assignment_is_excluded_from_validator_worklist(
    test_db, sample_source, validator_user
):
    await ValidationSession(
        source_id=str(sample_source.id),
        validator_id=str(validator_user.id),
        status="FLAGGED",
        flag_reason="Needs administrator attention",
        lock_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    ).insert()

    mine = await ValidationService.worklist(validator_user, view="mine")

    assert mine["items"] == []
    assert mine["pagination"]["total"] == 0


@pytest.mark.asyncio
async def test_tier_a_can_update_source_details(
    test_db, sample_source, validator_user
):
    await ValidationService.start(str(sample_source.id), validator_user)

    overview = make_overview()
    await overview.insert()

    workspace = await ValidationService.update_tier_a(
        str(sample_source.id),
        validator_user,
        sample_source.version,
        ArticleScopeClassification(articleType="Industry Overview", confidence=1),
        True,
        {
            "article_title": "Reviewed source title",
            "author": "Reviewed author",
            "article_text": "Reviewed source text",
        },
        str(overview.id),
        True,
    )

    assert workspace["source"]["article_title"] == "Reviewed source title"
    assert workspace["source"]["author"] == "Reviewed author"
    assert workspace["source"]["article_text"] == "Reviewed source text"
    refreshed_overview = await type(overview).get(overview.id, fetch_links=False)
    linked_source_id = (
        refreshed_overview.source.ref.id
        if hasattr(refreshed_overview.source, "ref")
        else refreshed_overview.source.id
    )
    assert str(linked_source_id) == str(sample_source.id)


@pytest.mark.asyncio
async def test_validator_can_link_edit_and_unlink_overview_without_deleting_it(
    test_db, sample_source, validator_user
):
    workspace = await ValidationService.start(
        str(sample_source.id), validator_user
    )
    overview = make_overview()
    await overview.insert()

    workspace = await ValidationService.update_overview_link(
        str(sample_source.id),
        validator_user,
        workspace["source"]["version"],
        str(overview.id),
    )
    assert str(overview.id) in str(workspace["source"]["overview"])
    linked_overview = await ValidationService.overview_workspace(
        str(sample_source.id), validator_user
    )

    saved = await ValidationService.update_overview(
        str(sample_source.id),
        validator_user,
        linked_overview["version"],
        make_overview_extract(
            summary="Validator-reviewed overview",
            countries=["Canada"],
        ),
    )
    assert saved["extracted_information"]["summary"] == (
        "Validator-reviewed overview"
    )

    workspace = await ValidationService.update_overview_link(
        str(sample_source.id),
        validator_user,
        workspace["source"]["version"],
        None,
    )
    assert workspace["source"]["overview"] is None
    retained = await type(overview).get(overview.id, fetch_links=False)
    assert retained is not None
    assert retained.source is None


@pytest.mark.asyncio
async def test_validator_can_add_and_remove_incident_link_without_deleting_record(
    test_db, sample_source, validator_user
):
    workspace = await ValidationService.start(
        str(sample_source.id), validator_user
    )
    incident = make_incident()
    await incident.insert()

    workspace = await ValidationService.add_incident_link(
        str(sample_source.id),
        str(incident.id),
        validator_user,
        workspace["source"]["version"],
    )
    assert [item["_id"] for item in workspace["incidents"]] == [
        str(incident.id)
    ]

    workspace = await ValidationService.remove_incident_link(
        str(sample_source.id),
        str(incident.id),
        validator_user,
        workspace["source"]["version"],
    )
    assert workspace["incidents"] == []
    retained = await type(incident).get(incident.id, fetch_links=False)
    assert retained is not None
    assert retained.sources == []


@pytest.mark.asyncio
async def test_relationship_change_rejects_stale_source_version(
    test_db, sample_source, validator_user
):
    workspace = await ValidationService.start(
        str(sample_source.id), validator_user
    )
    overview = make_overview()
    await overview.insert()
    stale_version = workspace["source"]["version"]
    await ValidationService.update_overview_link(
        str(sample_source.id),
        validator_user,
        stale_version,
        str(overview.id),
    )

    with pytest.raises(HTTPException) as exc:
        await ValidationService.update_overview_link(
            str(sample_source.id),
            validator_user,
            stale_version,
            None,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_revoking_validation_access_releases_active_work(
    test_db, sample_source, validator_user
):
    workspace = await ValidationService.start(
        str(sample_source.id), validator_user
    )

    updated = await ValidationService.admin_set_access(
        str(validator_user.id), False
    )

    session = await ValidationSession.get(workspace["session"]["_id"])
    assert updated["can_validate"] is False
    assert updated["released_sessions"] == 1
    assert session.status == "RELEASED"


@pytest.mark.asyncio
async def test_admin_can_promote_and_demote_another_registered_user(
    test_db, sample_user, admin_user
):
    promoted = await ValidationService.admin_set_admin_access(
        str(sample_user.id), True, admin_user
    )
    assert promoted["role"] == "admin"

    demoted = await ValidationService.admin_set_admin_access(
        str(sample_user.id), False, admin_user
    )
    assert demoted["role"] == "user"


@pytest.mark.asyncio
async def test_admin_cannot_remove_own_admin_access(test_db, admin_user):
    with pytest.raises(HTTPException) as exc:
        await ValidationService.admin_set_admin_access(
            str(admin_user.id), False, admin_user
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_admin_lists_are_server_paginated(test_db, admin_user):
    for index in range(3):
        await User(
            email=f"page-user-{index}@example.com",
            hashedPassword="unused",
            role="user",
        ).insert()
        await ValidationSession(
            source_id=str(ObjectId()),
            validator_id=str(admin_user.id),
            status="REPROCESSING_REQUIRED",
            lock_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ).insert()

    sessions = await ValidationService.admin_sessions(skip=1, limit=1)
    users = await ValidationService.admin_validators(skip=1, limit=2)
    reprocessing = await ValidationService.admin_reprocessing(skip=1, limit=1)

    assert sessions["pagination"] == {
        "total": 3,
        "skip": 1,
        "limit": 1,
        "has_more": True,
    }
    assert len(sessions["items"]) == 1
    assert users["pagination"] == {
        "total": 4,
        "skip": 1,
        "limit": 2,
        "has_more": True,
    }
    assert len(users["users"]) == 2
    assert reprocessing["pagination"] == {
        "total": 3,
        "skip": 1,
        "limit": 1,
        "has_more": True,
    }
    assert len(reprocessing["items"]) == 1


@pytest.mark.asyncio
async def test_admin_session_views_separate_flagged_and_completed(
    test_db, admin_user
):
    statuses = ["IN_PROGRESS", "FLAGGED", "COMPLETED"]
    for status_value in statuses:
        await ValidationSession(
            source_id=str(ObjectId()),
            validator_id=str(admin_user.id),
            status=status_value,
            lock_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ).insert()

    sessions = await ValidationService.admin_sessions(view="sessions")
    flagged = await ValidationService.admin_sessions(view="flagged")
    completed = await ValidationService.admin_sessions(view="completed")

    assert [row["session"]["status"] for row in sessions["items"]] == [
        "IN_PROGRESS"
    ]
    assert [row["session"]["status"] for row in flagged["items"]] == [
        "FLAGGED"
    ]
    assert [row["session"]["status"] for row in completed["items"]] == [
        "COMPLETED"
    ]
