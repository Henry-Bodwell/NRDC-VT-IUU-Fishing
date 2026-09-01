import re
from datetime import datetime, timedelta, timezone
from typing import Any, get_args, get_origin

from bson import ObjectId
from fastapi import HTTPException, status
from pydantic import BaseModel, TypeAdapter, ValidationError
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from app.audit.context import AuditContext
from app.audit.service import AuditService
from app.models.incident_data import ExtractedIncidentData
from app.models.incidents import IncidentReport, IndustryOverview
from app.models.overviews import IndustryOverviewExtract
from app.models.sources import ArticleScopeClassification, Source
from app.models.task import TaskStatus
from app.models.users import User
from app.models.validation import (
    ACTIVE_VALIDATION_STATUSES,
    ValidationSession,
)

LOCK_MINUTES = 15
INCIDENT_SCOPES = {"Single Incident", "Multiple Incidents"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # MongoDB may deserialize UTC timestamps without timezone information.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _link_id(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "ref"):
        return str(value.ref.id)
    value_id = getattr(value, "id", None)
    return str(value_id) if value_id is not None else None


def _dump(document: Any) -> dict:
    data = document.model_dump(mode="json", by_alias=True)
    data["_id"] = str(document.id)
    data.pop("id", None)
    return data


class ValidationService:
    @staticmethod
    def _is_expired(session: ValidationSession) -> bool:
        return _aware(session.lock_expires_at) <= _now()

    @staticmethod
    async def _expire_stale_sessions() -> None:
        sessions = await ValidationSession.find(
            {
                "status": {"$in": ACTIVE_VALIDATION_STATUSES},
                "lock_expires_at": {"$lte": _now()},
            }
        ).to_list()
        for session in sessions:
            session.status = "RELEASED"
            session.last_activity_at = _now()
            session.lock_expires_at = _now()
            with AuditContext.with_user("system:validation-lock-expiry"):
                await session.save()

    @staticmethod
    async def _source(source_id: str) -> Source:
        source = await Source.get(source_id, fetch_links=False)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source not found",
            )
        return source

    @staticmethod
    async def _incident(incident_id: str) -> IncidentReport:
        incident = await IncidentReport.get(incident_id, fetch_links=False)
        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )
        return incident

    @staticmethod
    async def _overview(overview_id: str) -> IndustryOverview:
        overview = await IndustryOverview.get(overview_id, fetch_links=False)
        if not overview:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Overview not found",
            )
        return overview

    @staticmethod
    async def _session(session_id: str) -> ValidationSession:
        session = await ValidationSession.get(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Validation session not found",
            )
        return session

    @staticmethod
    async def _active_session(source_id: str) -> ValidationSession | None:
        await ValidationService._expire_stale_sessions()
        return await ValidationSession.find_one(
            {
                "source_id": source_id,
                "status": {"$in": ACTIVE_VALIDATION_STATUSES},
            }
        )

    @staticmethod
    async def _owned_session(source_id: str, user: User) -> ValidationSession:
        session = await ValidationService._active_session(source_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Start a validation session before editing this source",
            )
        if session.validator_id != str(user.id):
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="This source is locked by another validator",
            )
        return session

    @staticmethod
    async def _editable_session(source_id: str, user: User) -> ValidationSession:
        session = await ValidationService._owned_session(source_id, user)
        if session.status == "FLAGGED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This session is flagged and must be resolved by an admin",
            )
        if session.status == "REPROCESSING_REQUIRED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Reprocessing is still in progress",
            )
        return session

    @staticmethod
    def _assert_version(document: Any, expected_version: int) -> None:
        if document.version != expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "version_conflict",
                    "message": "This record changed after it was loaded",
                    "current_version": document.version,
                },
            )

    @staticmethod
    def _touch(session: ValidationSession) -> None:
        session.last_activity_at = _now()
        session.lock_expires_at = _now() + timedelta(minutes=LOCK_MINUTES)

    @staticmethod
    async def _source_incidents(source: Source) -> list[IncidentReport]:
        incidents: list[IncidentReport] = []
        for link in source.incidents or []:
            incident_id = _link_id(link)
            if not incident_id:
                continue
            incident = await IncidentReport.get(incident_id, fetch_links=False)
            if incident:
                incidents.append(incident)
        return incidents

    @staticmethod
    def _verified_value(value: Any) -> bool:
        if isinstance(value, BaseModel):
            if "verified" in value.model_fields:
                return bool(getattr(value, "verified", False))
            if "validated" in value.model_fields:
                return bool(getattr(value, "validated", False))
            return False
        if isinstance(value, list):
            return bool(value) and all(
                ValidationService._verified_value(item) for item in value
            )
        return False

    @staticmethod
    def _set_verified(value: Any, reviewed: bool) -> None:
        if isinstance(value, BaseModel):
            if "verified" in value.model_fields:
                setattr(value, "verified", reviewed)
            elif "validated" in value.model_fields:
                setattr(value, "validated", reviewed)
        elif isinstance(value, list):
            for item in value:
                ValidationService._set_verified(item, reviewed)

    @staticmethod
    def _is_populated(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return bool(value)
        if isinstance(value, BaseModel):
            dumped = value.model_dump(exclude={"verified", "validated"})
            return any(ValidationService._is_populated(v) for v in dumped.values())
        return True

    @staticmethod
    def _annotation_contains_list(annotation: Any) -> bool:
        origin = get_origin(annotation)
        if origin is list:
            return True
        return any(
            ValidationService._annotation_contains_list(argument)
            for argument in get_args(annotation)
            if argument is not type(None)
        )

    @staticmethod
    def _annotation_model(annotation: Any) -> type[BaseModel] | None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation
        for argument in get_args(annotation):
            if argument is type(None):
                continue
            model = ValidationService._annotation_model(argument)
            if model:
                return model
        return None

    @staticmethod
    def _section_population(value: Any, annotation: Any) -> dict:
        if isinstance(value, list) or ValidationService._annotation_contains_list(
            annotation
        ):
            return {
                "filled": len(value) if isinstance(value, list) else 0,
                "total": None,
                "unit": "items",
            }

        model_type = type(value) if isinstance(value, BaseModel) else None
        if model_type is None:
            model_type = ValidationService._annotation_model(annotation)
        if model_type:
            # Validation markers track workflow state, not extracted content.
            field_names = [
                name
                for name in model_type.model_fields
                if name not in {"verified", "validated"}
            ]
            filled = sum(
                ValidationService._is_populated(getattr(value, name, None))
                for name in field_names
            )
            return {"filled": filled, "total": len(field_names), "unit": "fields"}

        return {
            "filled": int(ValidationService._is_populated(value)),
            "total": 1,
            "unit": "fields",
        }

    @staticmethod
    def incident_progress(
        incident: IncidentReport,
        session: ValidationSession | None,
    ) -> dict:
        classifications = incident.incident_classification.iuuClassifications
        tier_b_complete = bool(classifications) and all(
            classification.verified for classification in classifications
        )
        tier_b_blockers = []
        if not classifications:
            tier_b_blockers.append("Add at least one IUU classification")
        elif not tier_b_complete:
            tier_b_blockers.append("Validate every IUU classification")

        incident_id = str(incident.id)
        explicitly_reviewed = set(
            (session.reviewed_sections.get(incident_id, []) if session else [])
        )
        section_rows = []
        for section_name, field in ExtractedIncidentData.model_fields.items():
            value = getattr(incident.extracted_information, section_name)
            reviewed = (
                section_name in explicitly_reviewed
                or ValidationService._verified_value(value)
            )
            section_rows.append(
                {
                    "name": section_name,
                    "reviewed": reviewed,
                    "populated": ValidationService._is_populated(value),
                    "population": ValidationService._section_population(
                        value, field.annotation
                    ),
                }
            )

        reviewed_count = sum(1 for row in section_rows if row["reviewed"])
        tier_c_complete = reviewed_count == len(section_rows)
        tier_c_blockers = [
            f"Validate KDE section: {row['name']}"
            for row in section_rows
            if not row["reviewed"]
        ]
        blockers = tier_b_blockers + tier_c_blockers
        return {
            "incident_id": incident_id,
            "tier_b": {
                "complete": tier_b_complete,
                "reviewed": sum(1 for item in classifications if item.verified),
                "total": len(classifications),
                "blockers": tier_b_blockers,
            },
            "tier_c": {
                "complete": tier_c_complete,
                "reviewed": reviewed_count,
                "total": len(section_rows),
                "sections": section_rows,
                "blockers": tier_c_blockers,
            },
            "complete": not blockers,
            "marked_complete": incident.verified,
            "blockers": blockers,
        }

    @staticmethod
    async def source_progress(
        source: Source,
        session: ValidationSession | None,
        incidents: list[IncidentReport] | None = None,
    ) -> dict:
        incidents = (
            incidents
            if incidents is not None
            else await ValidationService._source_incidents(source)
        )
        incident_rows = [
            ValidationService.incident_progress(incident, session)
            for incident in incidents
        ]
        scope = source.article_scope.articleType if source.article_scope else None
        tier_a_complete = bool(source.validated_scope and scope)
        blockers: list[str] = []
        if not tier_a_complete:
            blockers.append("Complete Tier A source classification")
        incident_count = len(incidents)
        if scope == "Single Incident" and incident_count != 1:
            blockers.append("Single Incident scope requires exactly one incident")
        elif scope == "Multiple Incidents" and incident_count < 2:
            blockers.append("Multiple Incidents scope requires at least two incidents")
        elif scope not in INCIDENT_SCOPES and incident_count:
            blockers.append(f"{scope} scope cannot have linked incidents")
        for row in incident_rows:
            blockers.extend(row["blockers"])
            if row["complete"] and not row["marked_complete"]:
                blockers.append(
                    "Complete incident "
                    f"{row['incident_id']} before completing the source"
                )

        total_steps = 1 + (len(incident_rows) * 2)
        completed_steps = int(tier_a_complete) + sum(
            int(row["tier_b"]["complete"]) + int(row["tier_c"]["complete"])
            for row in incident_rows
        )
        return {
            "tier_a": {"complete": tier_a_complete, "scope": scope},
            "incidents": incident_rows,
            "completed_steps": completed_steps,
            "total_steps": total_steps,
            "percent": round((completed_steps / total_steps) * 100),
            "complete": not blockers,
            "blockers": blockers,
        }

    @staticmethod
    def _source_summary(source: Source) -> dict:
        text = source.article_text or ""
        return {
            "_id": str(source.id),
            "article_title": source.article_title,
            "article_preview": text[:220] + ("..." if len(text) > 220 else ""),
            "author": source.author,
            "publisher": source.publisher,
            "publication_date": source.publication_date,
            "article_scope": (
                source.article_scope.model_dump(mode="json")
                if source.article_scope
                else None
            ),
            "validated_scope": source.validated_scope,
            "source_type": source.source_type,
            "version": source.version,
            "incident_count": len(source.incidents or []),
        }

    @staticmethod
    def _session_data(session: ValidationSession | None) -> dict | None:
        return _dump(session) if session else None

    @staticmethod
    async def worklist(
        user: User,
        view: str = "available",
        search: str | None = None,
        skip: int = 0,
        limit: int = 25,
    ) -> dict:
        await ValidationService._expire_stale_sessions()
        query: dict = {}
        if search:
            pattern = re.escape(search.strip())
            query["$or"] = [
                {"article_title": {"$regex": pattern, "$options": "i"}},
                {"publisher": {"$regex": pattern, "$options": "i"}},
                {"url": {"$regex": pattern, "$options": "i"}},
            ]

        sessions = (
            await ValidationSession.find({})
            .sort([("updated_at", DESCENDING)])
            .to_list()
        )
        latest_by_source: dict[str, ValidationSession] = {}
        active_by_source: dict[str, ValidationSession] = {}
        for session in sessions:
            latest_by_source.setdefault(session.source_id, session)
            if session.status in ACTIVE_VALIDATION_STATUSES:
                active_by_source[session.source_id] = session

        active_ids = set(active_by_source)
        completed_ids = {
            source_id
            for source_id, session in latest_by_source.items()
            if session.status == "COMPLETED" and source_id not in active_ids
        }
        included_ids: set[str] | None = None
        excluded_ids: set[str] = set()
        if view == "available":
            excluded_ids = active_ids | completed_ids
        elif view == "mine":
            included_ids = {
                source_id
                for source_id, session in active_by_source.items()
                if session.validator_id == str(user.id) and session.status != "FLAGGED"
            }

        def object_ids(values: set[str]) -> list[ObjectId]:
            return [ObjectId(value) for value in values if ObjectId.is_valid(value)]

        if included_ids is not None:
            ids = object_ids(included_ids)
            if not ids:
                return {
                    "items": [],
                    "pagination": {
                        "total": 0,
                        "skip": skip,
                        "limit": limit,
                        "has_more": False,
                    },
                }
            query["_id"] = {"$in": ids}
        elif excluded_ids:
            query["_id"] = {"$nin": object_ids(excluded_ids)}

        source_query = Source.find(query, fetch_links=False)
        total = await source_query.count()
        sources = (
            await Source.find(query, fetch_links=False)
            .sort([("created_at", DESCENDING)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )

        rows = []
        for source in sources:
            source_id = str(source.id)
            active = active_by_source.get(source_id)
            latest = latest_by_source.get(source_id)
            mine = active is not None and active.validator_id == str(user.id)
            completed = latest is not None and latest.status == "COMPLETED"
            availability = (
                "mine"
                if mine
                else "locked" if active else "completed" if completed else "available"
            )
            incidents = await ValidationService._source_incidents(source)
            progress = await ValidationService.source_progress(
                source, active or latest, incidents
            )
            rows.append(
                {
                    "source": ValidationService._source_summary(source),
                    "session": ValidationService._session_data(active or latest),
                    "availability": availability,
                    "progress": progress,
                }
            )

        return {
            "items": rows,
            "pagination": {
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": skip + limit < total,
            },
        }

    @staticmethod
    async def start(source_id: str, user: User) -> dict:
        source = await ValidationService._source(source_id)
        active = await ValidationService._active_session(source_id)
        if active:
            if active.validator_id != str(user.id):
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="This source is already being validated",
                )
            ValidationService._touch(active)
            await active.save()
            return await ValidationService.source_workspace(source_id, user)

        incidents = await ValidationService._source_incidents(source)
        session = ValidationSession(
            source_id=source_id,
            validator_id=str(user.id),
            current_incident_id=str(incidents[0].id) if incidents else None,
            lock_expires_at=_now() + timedelta(minutes=LOCK_MINUTES),
        )
        try:
            await session.insert()
        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Another validator acquired this source",
            )
        return await ValidationService.source_workspace(source_id, user)

    @staticmethod
    async def heartbeat(source_id: str, user: User) -> dict:
        session = await ValidationService._owned_session(source_id, user)
        ValidationService._touch(session)
        await session.save()
        return ValidationService._session_data(session) or {}

    @staticmethod
    async def release(source_id: str, user: User) -> dict:
        session = await ValidationService._active_session(source_id)
        if not session:
            raise HTTPException(status_code=404, detail="Active session not found")
        if session.validator_id != str(user.id) and user.role != "admin":
            raise HTTPException(
                status_code=423,
                detail="Session belongs to another validator",
            )
        session.status = "RELEASED"
        session.last_activity_at = _now()
        session.lock_expires_at = _now()
        await session.save()
        return ValidationService._session_data(session) or {}

    @staticmethod
    async def flag(source_id: str, user: User, reason: str) -> dict:
        session = await ValidationService._editable_session(source_id, user)
        session.status = "FLAGGED"
        session.flag_reason = reason.strip()
        ValidationService._touch(session)
        await session.save()
        return ValidationService._session_data(session) or {}

    @staticmethod
    async def source_workspace(
        source_id: str,
        user: User,
        admin_read: bool = False,
    ) -> dict:
        source = await ValidationService._source(source_id)
        session = await ValidationService._active_session(source_id)
        if not admin_read:
            session = await ValidationService._owned_session(source_id, user)
        incidents = await ValidationService._source_incidents(source)
        source_data = _dump(source)
        source_data["incidents"] = [str(incident.id) for incident in incidents]
        return {
            "source": source_data,
            "incidents": [_dump(incident) for incident in incidents],
            "session": ValidationService._session_data(session),
            "progress": await ValidationService.source_progress(
                source, session, incidents
            ),
        }

    @staticmethod
    async def update_tier_a(
        source_id: str,
        user: User,
        expected_version: int,
        article_scope: ArticleScopeClassification,
        validated_scope: bool,
        source_updates: dict[str, Any] | None = None,
        overview_id: str | None = None,
        update_overview: bool = False,
    ) -> dict:
        session = await ValidationService._editable_session(source_id, user)
        source = await ValidationService._source(source_id)
        ValidationService._assert_version(source, expected_version)
        previous_scope = (
            source.article_scope.articleType if source.article_scope else None
        )
        scope_changed = previous_scope != article_scope.articleType
        for field, value in (source_updates or {}).items():
            setattr(source, field, value)

        previous_overview: IndustryOverview | None = None
        next_overview: IndustryOverview | None = None
        if update_overview:
            current_overview_id = _link_id(source.overview)
            clean_overview_id = overview_id.strip() if overview_id else None
            if clean_overview_id and not ObjectId.is_valid(clean_overview_id):
                raise HTTPException(status_code=422, detail="Invalid overview ID")
            if clean_overview_id != current_overview_id:
                if current_overview_id:
                    previous_overview = await IndustryOverview.get(
                        current_overview_id, fetch_links=False
                    )
                if clean_overview_id:
                    next_overview = await IndustryOverview.get(
                        clean_overview_id, fetch_links=False
                    )
                    if not next_overview:
                        raise HTTPException(
                            status_code=404, detail="Overview not found"
                        )
                    linked_source_id = _link_id(next_overview.source)
                    if linked_source_id and linked_source_id != source_id:
                        raise HTTPException(
                            status_code=409,
                            detail="Overview is already linked to another source",
                        )
                source.overview = next_overview

        source.article_scope = article_scope
        source.validated_scope = validated_scope if not scope_changed else False
        await source.save()
        if previous_overview and _link_id(previous_overview.source) == source_id:
            previous_overview.source = None
            await previous_overview.save()
        if next_overview:
            next_overview.source = source
            await next_overview.save()
        if scope_changed:
            session.status = "REPROCESSING_REQUIRED"
            session.task_id = None
        ValidationService._touch(session)
        await session.save()
        return await ValidationService.source_workspace(source_id, user)

    @staticmethod
    async def update_overview_link(
        source_id: str,
        user: User,
        expected_version: int,
        overview_id: str | None,
    ) -> dict:
        session = await ValidationService._editable_session(source_id, user)
        source = await ValidationService._source(source_id)
        ValidationService._assert_version(source, expected_version)
        current_id = _link_id(source.overview)
        next_id = overview_id.strip() if overview_id else None
        previous = (
            await IndustryOverview.get(current_id, fetch_links=False)
            if current_id
            else None
        )
        next_overview = await ValidationService._overview(next_id) if next_id else None

        if next_overview:
            linked_source_id = _link_id(next_overview.source)
            if linked_source_id and linked_source_id != source_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Overview is already linked to another source",
                )

        source.overview = next_overview
        await source.save()
        if previous and str(previous.id) != next_id:
            if _link_id(previous.source) == source_id:
                previous.source = None
                await previous.save()
        if next_overview and _link_id(next_overview.source) != source_id:
            next_overview.source = source
            await next_overview.save()
        ValidationService._touch(session)
        await session.save()
        return await ValidationService.source_workspace(source_id, user)

    @staticmethod
    async def overview_workspace(source_id: str, user: User) -> dict:
        await ValidationService._owned_session(source_id, user)
        source = await ValidationService._source(source_id)
        overview_id = _link_id(source.overview)
        if not overview_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This source has no linked overview",
            )
        overview = await ValidationService._overview(overview_id)
        linked_source_id = _link_id(overview.source)
        if linked_source_id and linked_source_id != source_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Overview relationship is inconsistent",
            )
        return _dump(overview)

    @staticmethod
    async def update_overview(
        source_id: str,
        user: User,
        expected_version: int,
        extracted_information: IndustryOverviewExtract,
    ) -> dict:
        session = await ValidationService._editable_session(source_id, user)
        source = await ValidationService._source(source_id)
        overview_id = _link_id(source.overview)
        if not overview_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This source has no linked overview",
            )
        overview = await ValidationService._overview(overview_id)
        linked_source_id = _link_id(overview.source)
        if linked_source_id and linked_source_id != source_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Overview relationship is inconsistent",
            )
        ValidationService._assert_version(overview, expected_version)
        overview.extracted_information = extracted_information
        overview.source = source
        await overview.save()
        ValidationService._touch(session)
        await session.save()
        return _dump(overview)

    @staticmethod
    async def _assert_relationship_available(
        incident: IncidentReport,
        source_id: str,
        user: User,
    ) -> None:
        linked_source_ids = {
            item
            for item in map(_link_id, incident.sources or [])
            if item and item != source_id
        }
        if not linked_source_ids:
            return
        await ValidationService._expire_stale_sessions()
        locked = await ValidationSession.find_one(
            {
                "source_id": {"$in": list(linked_source_ids)},
                "validator_id": {"$ne": str(user.id)},
                "status": {"$in": ACTIVE_VALIDATION_STATUSES},
            }
        )
        if locked:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Incident is part of another active validation session",
            )

    @staticmethod
    async def add_incident_link(
        source_id: str,
        incident_id: str,
        user: User,
        expected_version: int,
    ) -> dict:
        session = await ValidationService._editable_session(source_id, user)
        source = await ValidationService._source(source_id)
        ValidationService._assert_version(source, expected_version)
        incident = await ValidationService._incident(incident_id)
        await ValidationService._assert_relationship_available(
            incident, source_id, user
        )
        source_ids = {_link_id(item) for item in incident.sources or []}
        incident_ids = {_link_id(item) for item in source.incidents or []}
        if source_id in source_ids and incident_id in incident_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Incident is already linked to this source",
            )
        await incident.add_source(source)
        if not session.current_incident_id:
            session.current_incident_id = incident_id
        ValidationService._touch(session)
        await session.save()
        return await ValidationService.source_workspace(source_id, user)

    @staticmethod
    async def remove_incident_link(
        source_id: str,
        incident_id: str,
        user: User,
        expected_version: int,
    ) -> dict:
        session = await ValidationService._editable_session(source_id, user)
        source = await ValidationService._source(source_id)
        ValidationService._assert_version(source, expected_version)
        incident_ids = [_link_id(item) for item in source.incidents or []]
        if incident_id not in incident_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident is not linked to this source",
            )
        incident = await ValidationService._incident(incident_id)
        await ValidationService._assert_relationship_available(
            incident, source_id, user
        )
        incident_index = incident_ids.index(incident_id)
        if source.incident_passages is not None and len(
            source.incident_passages
        ) == len(incident_ids):
            source.incident_passages.pop(incident_index)
        # Remove the relationship only; the incident remains available elsewhere.
        await incident.remove_source(source)
        session.reviewed_sections.pop(incident_id, None)
        remaining_ids = [item for item in incident_ids if item != incident_id]
        if session.current_incident_id == incident_id:
            session.current_incident_id = remaining_ids[0] if remaining_ids else None
        ValidationService._touch(session)
        await session.save()
        return await ValidationService.source_workspace(source_id, user)

    @staticmethod
    async def start_reprocessing(
        source_id: str,
        user: User,
        expected_version: int,
        assumed_scope: str,
        background_tasks: Any,
    ) -> dict:
        session = await ValidationService._owned_session(source_id, user)
        if session.status == "FLAGGED":
            raise HTTPException(
                status_code=409,
                detail="Flagged sessions cannot reprocess",
            )
        if session.task_id and session.status == "REPROCESSING_REQUIRED":
            existing_task = await TaskStatus.find_one(
                TaskStatus.task_id == session.task_id
            )
            if existing_task and existing_task.status in {"pending", "processing"}:
                raise HTTPException(
                    status_code=409,
                    detail="Reprocessing is already running",
                )
        source = await ValidationService._source(source_id)
        ValidationService._assert_version(source, expected_version)
        task = TaskStatus(
            task_type="validation_reprocessing",
            user_id=str(user.id),
            input_params={"source_id": source_id, "assumed_scope": assumed_scope},
        )
        await task.insert()
        session.status = "REPROCESSING_REQUIRED"
        session.task_id = task.task_id
        ValidationService._touch(session)
        await session.save()
        background_tasks.add_task(
            ValidationService.run_reprocessing,
            str(session.id),
            source_id,
            assumed_scope,
            task.task_id,
            str(user.id),
        )
        return {
            "session": ValidationService._session_data(session),
            "task": _dump(task),
        }

    @staticmethod
    async def run_reprocessing(
        session_id: str,
        source_id: str,
        assumed_scope: str,
        task_id: str,
        user_id: str,
    ) -> None:
        from app.service.source_service import SourceService

        task = await TaskStatus.find_one(TaskStatus.task_id == task_id)
        session = await ValidationSession.get(session_id)
        try:
            if not task or not session:
                return
            await task.update_progress("reanalyzing", 10)
            source = await ValidationService._source(source_id)
            with AuditContext.with_user(user_id):
                refreshed = await SourceService._reclassify_source(
                    source, assumed_scope
                )
                refreshed.validated_scope = False
                await refreshed.save()
            await task.update_progress("refreshing_validation", 90)
            incidents = await ValidationService._source_incidents(refreshed)
            session.reviewed_sections = {}
            session.current_incident_id = str(incidents[0].id) if incidents else None
            validator = await User.get(session.validator_id)
            if validator and validator.can_validate:
                session.status = "READY_FOR_REVALIDATION"
            else:
                session.status = "RELEASED"
                session.lock_expires_at = _now()
            session.flag_reason = None
            ValidationService._touch(session)
            with AuditContext.with_user(user_id):
                await session.save()
            await task.mark_completed(
                {
                    "source_id": source_id,
                    "incident_ids": [str(item.id) for item in incidents],
                }
            )
        except Exception as exc:
            if task:
                await task.mark_failed(str(exc))
            if session:
                session.status = "FLAGGED"
                session.flag_reason = f"Reprocessing failed: {exc}"
                with AuditContext.with_user(user_id):
                    await session.save()

    @staticmethod
    async def _incident_session(
        incident: IncidentReport,
        user: User,
    ) -> tuple[str, ValidationSession]:
        source_ids = [
            source_id
            for source_id in map(_link_id, incident.sources or [])
            if source_id
        ]
        if not source_ids:
            raise HTTPException(
                status_code=409,
                detail="Incident is not linked to a source",
            )
        await ValidationService._expire_stale_sessions()
        session = await ValidationSession.find_one(
            {
                "source_id": {"$in": source_ids},
                "validator_id": str(user.id),
                "status": {"$in": ACTIVE_VALIDATION_STATUSES},
            }
        )
        if not session:
            raise HTTPException(status_code=423, detail="Active source lease required")
        if session.status in {"FLAGGED", "REPROCESSING_REQUIRED"}:
            raise HTTPException(status_code=409, detail="Session is not editable")
        return session.source_id, session

    @staticmethod
    async def incident_workspace(
        incident_id: str,
        user: User,
        admin_read: bool = False,
    ) -> dict:
        incident = await ValidationService._incident(incident_id)
        if admin_read:
            source_ids = [
                source_id
                for source_id in map(_link_id, incident.sources or [])
                if source_id
            ]
            if not source_ids:
                raise HTTPException(
                    status_code=409,
                    detail="Incident is not linked to a source",
                )
            source_id = source_ids[0]
            session = await ValidationService._active_session(source_id)
        else:
            source_id, session = await ValidationService._incident_session(
                incident, user
            )
        return {
            "source_id": source_id,
            "incident": _dump(incident),
            "session": ValidationService._session_data(session),
            "progress": ValidationService.incident_progress(incident, session),
        }

    @staticmethod
    async def update_classifications(
        incident_id: str,
        user: User,
        expected_version: int,
        incident_classification: Any,
    ) -> dict:
        incident = await ValidationService._incident(incident_id)
        _, session = await ValidationService._incident_session(incident, user)
        ValidationService._assert_version(incident, expected_version)
        incident.incident_classification = incident_classification
        incident.verified = False
        await incident.save()
        ValidationService._touch(session)
        await session.save()
        return await ValidationService.incident_workspace(incident_id, user)

    @staticmethod
    async def update_section(
        incident_id: str,
        section_name: str,
        user: User,
        expected_version: int,
        value: Any,
        reviewed: bool,
    ) -> dict:
        if section_name not in ExtractedIncidentData.model_fields:
            raise HTTPException(status_code=404, detail="Unknown KDE section")
        incident = await ValidationService._incident(incident_id)
        _, session = await ValidationService._incident_session(incident, user)
        ValidationService._assert_version(incident, expected_version)
        annotation = ExtractedIncidentData.model_fields[section_name].annotation
        try:
            parsed = TypeAdapter(annotation).validate_python(value)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=exc.errors(),
            )
        ValidationService._set_verified(parsed, reviewed)
        setattr(incident.extracted_information, section_name, parsed)
        incident.verified = False

        reviewed_sections = set(session.reviewed_sections.get(str(incident.id), []))
        if reviewed:
            reviewed_sections.add(section_name)
        else:
            reviewed_sections.discard(section_name)
        session.reviewed_sections[str(incident.id)] = sorted(reviewed_sections)
        await incident.save()
        ValidationService._touch(session)
        await session.save()
        return await ValidationService.incident_workspace(incident_id, user)

    @staticmethod
    async def complete_incident(incident_id: str, user: User) -> dict:
        incident = await ValidationService._incident(incident_id)
        _, session = await ValidationService._incident_session(incident, user)
        progress = ValidationService.incident_progress(incident, session)
        if progress["blockers"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "validation_incomplete",
                    "blockers": progress["blockers"],
                },
            )
        incident.verified = True
        await incident.save()
        ValidationService._touch(session)
        await session.save()
        return await ValidationService.incident_workspace(incident_id, user)

    @staticmethod
    async def complete_source(source_id: str, user: User) -> dict:
        session = await ValidationService._editable_session(source_id, user)
        source = await ValidationService._source(source_id)
        incidents = await ValidationService._source_incidents(source)
        progress = await ValidationService.source_progress(source, session, incidents)
        if progress["blockers"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "validation_incomplete",
                    "blockers": progress["blockers"],
                },
            )
        session.status = "COMPLETED"
        session.completed_at = _now()
        session.last_activity_at = _now()
        session.lock_expires_at = _now()
        await session.save()
        return {
            "session": ValidationService._session_data(session),
            "progress": progress,
        }

    @staticmethod
    async def admin_overview() -> dict:
        await ValidationService._expire_stale_sessions()
        sessions = await ValidationSession.find({}).to_list()
        status_counts: dict[str, int] = {}
        for session in sessions:
            status_counts[session.status] = status_counts.get(session.status, 0) + 1
        source_total = await Source.find({}).count()
        active_source_ids = {
            item.source_id
            for item in sessions
            if item.status in ACTIVE_VALIDATION_STATUSES
        }
        completed_source_ids = {
            item.source_id for item in sessions if item.status == "COMPLETED"
        }
        processing_tasks = await TaskStatus.find(
            {
                "task_type": "validation_reprocessing",
                "status": {"$in": ["pending", "processing"]},
            }
        ).count()
        return {
            "sources": {
                "total": source_total,
                "available": max(
                    source_total - len(active_source_ids) - len(completed_source_ids),
                    0,
                ),
                "active": len(active_source_ids),
                "completed": len(completed_source_ids),
            },
            "sessions_by_status": status_counts,
            "reprocessing": processing_tasks,
        }

    @staticmethod
    async def admin_sessions(
        view: str = "sessions",
        session_status: str | None = None,
        validator_id: str | None = None,
        skip: int = 0,
        limit: int = 25,
    ) -> dict:
        await ValidationService._expire_stale_sessions()
        query: dict = {}
        if view == "flagged":
            query["status"] = "FLAGGED"
        elif view == "completed":
            query["status"] = "COMPLETED"
        elif session_status:
            query["status"] = session_status
        else:
            # Keep the operator queues disjoint to avoid duplicate session rows.
            query["status"] = {"$nin": ["FLAGGED", "COMPLETED"]}
        if validator_id:
            query["validator_id"] = validator_id
        total = await ValidationSession.find(query).count()
        sessions = (
            await ValidationSession.find(query)
            .sort([("updated_at", DESCENDING)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )
        rows = []
        for session in sessions:
            source = await Source.get(session.source_id, fetch_links=False)
            validator = await User.get(session.validator_id)
            rows.append(
                {
                    "session": ValidationService._session_data(session),
                    "source": (
                        ValidationService._source_summary(source) if source else None
                    ),
                    "validator": (
                        {
                            "_id": str(validator.id),
                            "name": validator.name,
                            "email": validator.email,
                        }
                        if validator
                        else None
                    ),
                }
            )
        return {
            "items": rows,
            "pagination": {
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": skip + limit < total,
            },
        }

    @staticmethod
    async def admin_session_detail(session_id: str, admin: User) -> dict:
        session = await ValidationService._session(session_id)
        source = await ValidationService._source(session.source_id)
        incidents = await ValidationService._source_incidents(source)
        source_data = _dump(source)
        source_data["incidents"] = [str(item.id) for item in incidents]
        return {
            "session": ValidationService._session_data(session),
            "source": source_data,
            "incidents": [_dump(item) for item in incidents],
            "progress": await ValidationService.source_progress(
                source, session, incidents
            ),
        }

    @staticmethod
    async def admin_release(session_id: str) -> dict:
        session = await ValidationService._session(session_id)
        session.status = "RELEASED"
        session.lock_expires_at = _now()
        session.last_activity_at = _now()
        await session.save()
        return ValidationService._session_data(session) or {}

    @staticmethod
    async def admin_take_over(session_id: str, admin: User) -> dict:
        if not admin.can_validate:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Grant yourself validation access before taking over work",
            )
        session = await ValidationService._session(session_id)
        if session.status in {"COMPLETED", "RELEASED"}:
            raise HTTPException(
                status_code=409,
                detail="Reopen the session before takeover",
            )
        session.validator_id = str(admin.id)
        session.status = "IN_PROGRESS"
        session.flag_reason = None
        ValidationService._touch(session)
        await session.save()
        return ValidationService._session_data(session) or {}

    @staticmethod
    async def admin_resolve_flag(session_id: str, action: str) -> dict:
        session = await ValidationService._session(session_id)
        if session.status != "FLAGGED":
            raise HTTPException(status_code=409, detail="Session is not flagged")
        session.flag_reason = None
        if action == "release":
            session.status = "RELEASED"
            session.lock_expires_at = _now()
        else:
            session.status = "IN_PROGRESS"
            ValidationService._touch(session)
        await session.save()
        return ValidationService._session_data(session) or {}

    @staticmethod
    async def admin_validators(skip: int = 0, limit: int = 25) -> dict:
        total = await User.find({}).count()
        users = (
            await User.find({})
            .sort([("name", 1), ("email", 1)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )
        return {
            "users": [
                {
                    "_id": str(user.id),
                    "name": user.name,
                    "email": user.email,
                    "role": user.role,
                    "can_validate": user.can_validate,
                    "is_active": user.is_active,
                }
                for user in users
            ],
            "pagination": {
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": skip + limit < total,
            },
        }

    @staticmethod
    async def admin_set_access(user_id: str, can_validate: bool) -> dict:
        user = await User.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if can_validate and not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Activate the account before granting validation access",
            )
        original_state = user.model_dump(exclude={"id"})
        user.can_validate = can_validate
        await user.save()
        await AuditService.log_update(user, original_state)
        released_sessions = 0
        if not can_validate:
            sessions = await ValidationSession.find(
                {
                    "validator_id": user_id,
                    "status": {"$in": ACTIVE_VALIDATION_STATUSES},
                }
            ).to_list()
            for session in sessions:
                session.status = "RELEASED"
                session.last_activity_at = _now()
                session.lock_expires_at = _now()
                await session.save()
                released_sessions += 1
        return {
            "_id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "can_validate": user.can_validate,
            "is_active": user.is_active,
            "released_sessions": released_sessions,
        }

    @staticmethod
    async def admin_set_admin_access(
        user_id: str,
        is_admin: bool,
        acting_admin: User,
    ) -> dict:
        user = await User.get(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if is_admin and not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Activate the account before granting admin access",
            )
        if not is_admin and str(user.id) == str(acting_admin.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot remove your own admin access",
            )
        if not is_admin and user.role == "admin":
            remaining_admins = await User.find(
                {
                    "_id": {"$ne": user.id},
                    "role": "admin",
                    "is_active": True,
                }
            ).count()
            if remaining_admins == 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="At least one active administrator is required",
                )
        original_state = user.model_dump(exclude={"id"})
        user.role = "admin" if is_admin else "user"
        await user.save()
        await AuditService.log_update(user, original_state)
        return {
            "_id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "can_validate": user.can_validate,
            "is_active": user.is_active,
        }

    @staticmethod
    async def admin_reprocessing(skip: int = 0, limit: int = 25) -> dict:
        query = {
            "$or": [
                {
                    "status": {
                        "$in": [
                            "REPROCESSING_REQUIRED",
                            "READY_FOR_REVALIDATION",
                        ]
                    }
                },
                {"task_id": {"$ne": None}},
            ]
        }
        total = await ValidationSession.find(query).count()
        sessions = (
            await ValidationSession.find(query)
            .sort([("updated_at", DESCENDING)])
            .skip(skip)
            .limit(limit)
            .to_list()
        )
        rows = []
        for session in sessions:
            task = (
                await TaskStatus.find_one(TaskStatus.task_id == session.task_id)
                if session.task_id
                else None
            )
            rows.append(
                {
                    "session": ValidationService._session_data(session),
                    "task": _dump(task) if task else None,
                }
            )
        return {
            "items": rows,
            "pagination": {
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": skip + limit < total,
            },
        }

    @staticmethod
    async def admin_reopen(
        session_id: str,
        admin: User,
        validator_id: str | None = None,
    ) -> dict:
        session = await ValidationService._session(session_id)
        if session.status not in {"COMPLETED", "RELEASED"}:
            raise HTTPException(
                status_code=409,
                detail="Only closed sessions can be reopened",
            )
        active = await ValidationService._active_session(session.source_id)
        if active and str(active.id) != str(session.id):
            raise HTTPException(
                status_code=423,
                detail="Source already has an active session",
            )
        assignee_id = validator_id or session.validator_id or str(admin.id)
        assignee = await User.get(assignee_id)
        if not assignee or not assignee.can_validate:
            raise HTTPException(
                status_code=422,
                detail="Assignee does not have validation access",
            )
        session.validator_id = assignee_id
        session.status = "IN_PROGRESS"
        session.completed_at = None
        session.flag_reason = None
        ValidationService._touch(session)
        try:
            await session.save()
        except DuplicateKeyError:
            raise HTTPException(
                status_code=423,
                detail="Source already has an active session",
            )
        return ValidationService._session_data(session) or {}
