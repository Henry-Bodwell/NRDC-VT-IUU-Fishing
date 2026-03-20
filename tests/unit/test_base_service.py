"""
Unit tests for the base Service class (deep_merge, update_model, delete)
and the module-level helpers (_filter_valid_fields, _validate_no_link_updates).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException
from pydantic import BaseModel

from app.service.service import Service, _filter_valid_fields, _validate_no_link_updates


# ---------------------------------------------------------------------------
# Service.deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_shallow_merge(self):
        result = Service.deep_merge({"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        existing = {"a": {"x": 1, "y": 2}, "b": 10}
        update = {"a": {"y": 99, "z": 3}}
        result = Service.deep_merge(existing, update)
        assert result == {"a": {"x": 1, "y": 99, "z": 3}, "b": 10}

    def test_deeply_nested_merge(self):
        existing = {"a": {"b": {"c": 1, "d": 2}}}
        update = {"a": {"b": {"d": 99, "e": 3}}}
        result = Service.deep_merge(existing, update)
        assert result == {"a": {"b": {"c": 1, "d": 99, "e": 3}}}

    def test_overwrite_dict_with_scalar(self):
        result = Service.deep_merge({"a": {"nested": 1}}, {"a": "flat"})
        assert result == {"a": "flat"}

    def test_overwrite_scalar_with_dict(self):
        result = Service.deep_merge({"a": "flat"}, {"a": {"nested": 1}})
        assert result == {"a": {"nested": 1}}

    def test_empty_update(self):
        existing = {"a": 1}
        assert Service.deep_merge(existing, {}) == {"a": 1}

    def test_empty_existing(self):
        assert Service.deep_merge({}, {"a": 1}) == {"a": 1}

    def test_does_not_mutate_original(self):
        existing = {"a": {"x": 1}}
        Service.deep_merge(existing, {"a": {"y": 2}})
        assert existing == {"a": {"x": 1}}


# ---------------------------------------------------------------------------
# _filter_valid_fields
# ---------------------------------------------------------------------------


class _FakeModel(BaseModel):
    name: str = ""
    age: int = 0


class TestFilterValidFields:
    def test_keeps_valid_fields(self):
        result = _filter_valid_fields(_FakeModel, {"name": "Alice", "age": 30})
        assert result == {"name": "Alice", "age": 30}

    def test_strips_invalid_fields(self):
        result = _filter_valid_fields(
            _FakeModel, {"name": "Alice", "bogus": 99, "extra": "x"}
        )
        assert result == {"name": "Alice"}

    def test_empty_input(self):
        assert _filter_valid_fields(_FakeModel, {}) == {}


# ---------------------------------------------------------------------------
# _validate_no_link_updates
# ---------------------------------------------------------------------------


class TestValidateNoLinkUpdates:
    def test_no_link_fields_passes(self):
        # Should not raise
        _validate_no_link_updates(_FakeModel, {"name": "ok"}, "fake")

    def test_link_field_raises(self):
        """Uses real Source model which has Link fields (incidents, overview)."""
        from app.models.sources import Source

        with pytest.raises(HTTPException) as exc_info:
            _validate_no_link_updates(Source, {"incidents": []}, "source")
        assert exc_info.value.status_code == 400
        assert "incidents" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# Service.delete (unit -- mocked DB)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        mock_cls = MagicMock()
        mock_cls.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await Service.delete(
                model_cls=mock_cls, model_id="missing-id", model_name="widget"
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success(self):
        mock_instance = AsyncMock()
        mock_cls = MagicMock()
        mock_cls.get = AsyncMock(return_value=mock_instance)

        result = await Service.delete(
            model_cls=mock_cls, model_id="some-id", model_name="widget"
        )
        assert result is True
        mock_instance.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_db_error_raises_500(self):
        mock_instance = AsyncMock()
        mock_instance.delete.side_effect = RuntimeError("connection lost")
        mock_cls = MagicMock()
        mock_cls.get = AsyncMock(return_value=mock_instance)

        with pytest.raises(HTTPException) as exc_info:
            await Service.delete(
                model_cls=mock_cls, model_id="some-id", model_name="widget"
            )
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Service.update_model (unit -- mocked DB)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestServiceUpdateModel:
    @pytest.mark.asyncio
    async def test_update_not_found(self):
        mock_cls = MagicMock()
        mock_cls.get = AsyncMock(return_value=None)
        mock_cls.model_fields = {}

        with pytest.raises(HTTPException) as exc_info:
            await Service.update_model(
                model_cls=mock_cls,
                model_id="missing",
                update_data={"status": "modified"},
                model_name="widget",
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_sets_scalar_field(self):
        mock_instance = MagicMock()
        mock_instance.status = "extracted"
        mock_instance.replace = AsyncMock()

        mock_cls = MagicMock()
        mock_cls.get = AsyncMock(return_value=mock_instance)
        mock_cls.model_fields = {
            "status": MagicMock(annotation="str"),
        }

        result = await Service.update_model(
            model_cls=mock_cls,
            model_id="some-id",
            update_data={"status": "modified"},
            model_name="widget",
        )
        assert result.status == "modified"
        mock_instance.replace.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_deep_merges_nested_dict(self):
        """When the existing value is a dict and the update is a dict, deep merge."""
        mock_instance = MagicMock()
        mock_instance.metadata = {"a": 1, "b": 2}
        mock_instance.replace = AsyncMock()

        mock_cls = MagicMock()
        mock_cls.get = AsyncMock(return_value=mock_instance)
        mock_cls.model_fields = {
            "metadata": MagicMock(annotation="dict"),
        }

        await Service.update_model(
            model_cls=mock_cls,
            model_id="some-id",
            update_data={"metadata": {"b": 99, "c": 3}},
            model_name="widget",
        )
        assert mock_instance.metadata == {"a": 1, "b": 99, "c": 3}

    @pytest.mark.asyncio
    async def test_update_replace_failure_raises_500(self):
        mock_instance = MagicMock()
        mock_instance.status = "extracted"
        mock_instance.replace = AsyncMock(side_effect=RuntimeError("db error"))

        mock_cls = MagicMock()
        mock_cls.get = AsyncMock(return_value=mock_instance)
        mock_cls.model_fields = {
            "status": MagicMock(annotation="str"),
        }

        with pytest.raises(HTTPException) as exc_info:
            await Service.update_model(
                model_cls=mock_cls,
                model_id="some-id",
                update_data={"status": "modified"},
                model_name="widget",
            )
        assert exc_info.value.status_code == 500
