from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.audit.context import AuditContext
from app.auth import get_current_validation_admin, get_current_validator_user
from app.models.users import User
from app.routes.helpers import valid_object_id
from app.service.validation_service import ValidationService
from app.validation_interfaces import (
    AdminReopenRequest,
    AdminRoleAccessRequest,
    AdminResolveFlagRequest,
    AdminValidationAccessRequest,
    ClassificationUpdateRequest,
    FlagValidationRequest,
    ReprocessValidationRequest,
    SectionUpdateRequest,
    SourceRelationshipRequest,
    TierAUpdateRequest,
    OverviewUpdateRequest,
)

router = APIRouter(prefix="/validation", tags=["validation"])


@router.get("/worklist")
async def validation_worklist(
    view: Literal["available", "mine"] = "available",
    search: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_validator_user),
):
    return await ValidationService.worklist(
        current_user, view=view, search=search, skip=skip, limit=limit
    )


@router.post("/sources/{source_id}/start")
async def start_validation(
    source_id: str,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.start(source_id, current_user)


@router.post("/sources/{source_id}/heartbeat")
async def heartbeat_validation(
    source_id: str,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.heartbeat(source_id, current_user)


@router.post("/sources/{source_id}/release")
async def release_validation(
    source_id: str,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.release(source_id, current_user)


@router.post("/sources/{source_id}/flag")
async def flag_validation(
    source_id: str,
    body: FlagValidationRequest,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.flag(source_id, current_user, body.reason)


@router.get("/sources/{source_id}")
async def get_validation_source(
    source_id: str,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    return await ValidationService.source_workspace(
        source_id,
        current_user,
        admin_read=current_user.role == "admin",
    )


@router.put("/sources/{source_id}/tier-a")
async def update_validation_tier_a(
    source_id: str,
    body: TierAUpdateRequest,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    editable_source_fields = {
        "article_title",
        "url",
        "article_text",
        "author",
        "publisher",
        "publication_date",
    }
    source_updates = body.model_dump(
        include=editable_source_fields,
        exclude_unset=True,
    )
    if source_updates.get("article_text") is None:
        source_updates.pop("article_text", None)
    update_overview = "overview_id" in body.model_fields_set
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.update_tier_a(
            source_id,
            current_user,
            body.expected_version,
            body.article_scope,
            body.validated_scope,
            source_updates,
            body.overview_id,
            update_overview,
        )


@router.put("/sources/{source_id}/overview-link")
async def update_validation_overview_link(
    source_id: str,
    body: SourceRelationshipRequest,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    if body.target_id:
        valid_object_id(body.target_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.update_overview_link(
            source_id,
            current_user,
            body.expected_version,
            body.target_id,
        )


@router.get("/sources/{source_id}/overview")
async def get_validation_overview(
    source_id: str,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    return await ValidationService.overview_workspace(source_id, current_user)


@router.put("/sources/{source_id}/overview")
async def update_validation_overview(
    source_id: str,
    body: OverviewUpdateRequest,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.update_overview(
            source_id,
            current_user,
            body.expected_version,
            body.extracted_information,
        )


@router.post("/sources/{source_id}/incidents")
async def add_validation_incident(
    source_id: str,
    body: SourceRelationshipRequest,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    if not body.target_id:
        raise HTTPException(status_code=422, detail="Incident ID is required")
    valid_object_id(body.target_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.add_incident_link(
            source_id,
            body.target_id,
            current_user,
            body.expected_version,
        )


@router.delete("/sources/{source_id}/incidents/{incident_id}")
async def remove_validation_incident(
    source_id: str,
    incident_id: str,
    body: SourceRelationshipRequest,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    valid_object_id(incident_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.remove_incident_link(
            source_id,
            incident_id,
            current_user,
            body.expected_version,
        )


@router.post("/sources/{source_id}/reprocess")
async def reprocess_validation_source(
    source_id: str,
    body: ReprocessValidationRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.start_reprocessing(
            source_id,
            current_user,
            body.expected_version,
            body.assumed_scope,
            background_tasks,
        )


@router.get("/incidents/{incident_id}")
async def get_validation_incident(
    incident_id: str,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(incident_id)
    return await ValidationService.incident_workspace(
        incident_id,
        current_user,
        admin_read=current_user.role == "admin",
    )


@router.put("/incidents/{incident_id}/classifications")
async def update_validation_classifications(
    incident_id: str,
    body: ClassificationUpdateRequest,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(incident_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.update_classifications(
            incident_id,
            current_user,
            body.expected_version,
            body.incident_classification,
        )


@router.put("/incidents/{incident_id}/sections/{section_name}")
async def update_validation_section(
    incident_id: str,
    section_name: str,
    body: SectionUpdateRequest,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(incident_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.update_section(
            incident_id,
            section_name,
            current_user,
            body.expected_version,
            body.value,
            body.reviewed,
        )


@router.post("/incidents/{incident_id}/complete")
async def complete_validation_incident(
    incident_id: str,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(incident_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.complete_incident(incident_id, current_user)


@router.post("/sources/{source_id}/complete")
async def complete_validation_source(
    source_id: str,
    current_user: User = Depends(get_current_validator_user),
):
    valid_object_id(source_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.complete_source(source_id, current_user)


@router.get("/admin/overview")
async def validation_admin_overview(
    current_user: User = Depends(get_current_validation_admin),
):
    return await ValidationService.admin_overview()


@router.get("/admin/sessions")
async def validation_admin_sessions(
    view: Literal["sessions", "flagged", "completed"] = "sessions",
    status_filter: str | None = Query(default=None, alias="status"),
    validator_id: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_validation_admin),
):
    return await ValidationService.admin_sessions(
        view=view,
        session_status=status_filter,
        validator_id=validator_id,
        skip=skip,
        limit=limit,
    )


@router.get("/admin/sessions/{session_id}")
async def validation_admin_session_detail(
    session_id: str,
    current_user: User = Depends(get_current_validation_admin),
):
    valid_object_id(session_id)
    return await ValidationService.admin_session_detail(session_id, current_user)


@router.post("/admin/sessions/{session_id}/release")
async def validation_admin_release(
    session_id: str,
    current_user: User = Depends(get_current_validation_admin),
):
    valid_object_id(session_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.admin_release(session_id)


@router.post("/admin/sessions/{session_id}/take-over")
async def validation_admin_take_over(
    session_id: str,
    current_user: User = Depends(get_current_validation_admin),
):
    valid_object_id(session_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.admin_take_over(session_id, current_user)


@router.post("/admin/sessions/{session_id}/resolve-flag")
async def validation_admin_resolve_flag(
    session_id: str,
    body: AdminResolveFlagRequest,
    current_user: User = Depends(get_current_validation_admin),
):
    valid_object_id(session_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.admin_resolve_flag(session_id, body.action)


@router.post("/admin/sessions/{session_id}/reopen")
async def validation_admin_reopen(
    session_id: str,
    body: AdminReopenRequest,
    current_user: User = Depends(get_current_validation_admin),
):
    valid_object_id(session_id)
    if body.validator_id:
        valid_object_id(body.validator_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.admin_reopen(
            session_id, current_user, body.validator_id
        )


@router.get("/admin/validators")
async def validation_admin_validators(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_validation_admin),
):
    return await ValidationService.admin_validators(skip=skip, limit=limit)


@router.patch("/admin/validators/{user_id}/validation-access")
async def validation_admin_set_access(
    user_id: str,
    body: AdminValidationAccessRequest,
    current_user: User = Depends(get_current_validation_admin),
):
    valid_object_id(user_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.admin_set_access(user_id, body.can_validate)


@router.patch("/admin/users/{user_id}/admin-access")
async def validation_admin_set_admin_access(
    user_id: str,
    body: AdminRoleAccessRequest,
    current_user: User = Depends(get_current_validation_admin),
):
    valid_object_id(user_id)
    with AuditContext.with_user(str(current_user.id)):
        return await ValidationService.admin_set_admin_access(
            user_id,
            body.is_admin,
            current_user,
        )


@router.get("/admin/reprocessing")
async def validation_admin_reprocessing(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_validation_admin),
):
    return await ValidationService.admin_reprocessing(skip=skip, limit=limit)
