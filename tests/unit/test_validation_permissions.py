import pytest
from fastapi import HTTPException
from types import SimpleNamespace

from app.auth import get_current_admin_user, get_current_validator_user


def make_user(role: str = "user", can_validate: bool = False):
    return SimpleNamespace(
        id="test-user-id",
        email=f"{role}-{can_validate}@example.com",
        role=role,
        can_validate=can_validate,
    )


@pytest.mark.asyncio
async def test_validator_dependency_rejects_regular_user():
    with pytest.raises(HTTPException) as exc:
        await get_current_validator_user(make_user())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "can_validate"),
    [("user", True), ("validator", True), ("admin", True)],
)
async def test_validator_dependency_accepts_authorized_users(role, can_validate):
    user = make_user(role=role, can_validate=can_validate)
    assert await get_current_validator_user(user) is user


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "validator", "admin"])
async def test_validation_access_toggle_applies_to_every_role(role):
    with pytest.raises(HTTPException) as exc:
        await get_current_validator_user(make_user(role=role, can_validate=False))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_validation_admin_dependency_rejects_validator():
    with pytest.raises(HTTPException) as exc:
        await get_current_admin_user(make_user(role="validator"))
    assert exc.value.status_code == 403
