from enum import Enum


class OperationType(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ChangeType(str, Enum):
    JSON_PATCH = "json_patch"
    TEXT_DIFF = "text_diff"
