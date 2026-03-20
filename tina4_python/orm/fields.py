# Tina4 ORM Fields — Type definitions for model columns.
"""
Fields define column types, constraints, and defaults for ORM models.

    class User(ORM):
        id = Field(int, primary_key=True)
        name = Field(str, required=True, min_length=1, max_length=100)
        email = Field(str, regex=r'^[^@]+@[^@]+\\.[^@]+$')
        role = Field(str, choices=["admin", "user", "guest"])
        active = Field(bool, default=True)
"""
import re as _re
from datetime import datetime


class Field:
    """Generic field descriptor — maps a Python type to a database column."""

    def __init__(
        self,
        field_type: type = str,
        *,
        primary_key: bool = False,
        auto_increment: bool = False,
        required: bool = False,
        default=None,
        column: str = None,
        min_length: int = None,
        max_length: int = None,
        min_value: float | int = None,
        max_value: float | int = None,
        regex: str = None,
        choices: list = None,
        validator: callable = None,
    ):
        self.field_type = field_type
        self.primary_key = primary_key
        self.auto_increment = auto_increment
        self.required = required
        self.default = default
        self.column = column  # Override DB column name
        self.name = None  # Set by ORM metaclass

        # Validation constraints
        self.min_length = min_length
        self.max_length = max_length
        self.min_value = min_value
        self.max_value = max_value
        self.regex = _re.compile(regex) if regex else None
        self.regex_pattern = regex  # Keep original for error messages
        self.choices = choices
        self.validator = validator  # Custom callable(value) → raises ValueError

    def validate(self, value):
        """Validate and coerce value to the field type."""
        if value is None:
            if self.required and self.default is None:
                raise ValueError(f"Field '{self.name}' is required")
            return self.default

        # Type coercion
        try:
            if self.field_type == bool and isinstance(value, int):
                value = bool(value)
            else:
                value = self.field_type(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Field '{self.name}': cannot convert {value!r} to {self.field_type.__name__}"
            ) from e

        # String length constraints
        if isinstance(value, str):
            if self.min_length is not None and len(value) < self.min_length:
                raise ValueError(
                    f"Field '{self.name}': minimum length is {self.min_length}, got {len(value)}"
                )
            if self.max_length is not None and len(value) > self.max_length:
                raise ValueError(
                    f"Field '{self.name}': maximum length is {self.max_length}, got {len(value)}"
                )

        # Numeric range constraints
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.min_value is not None and value < self.min_value:
                raise ValueError(
                    f"Field '{self.name}': minimum value is {self.min_value}, got {value}"
                )
            if self.max_value is not None and value > self.max_value:
                raise ValueError(
                    f"Field '{self.name}': maximum value is {self.max_value}, got {value}"
                )

        # Regex pattern
        if self.regex and isinstance(value, str):
            if not self.regex.match(value):
                raise ValueError(
                    f"Field '{self.name}': value does not match pattern {self.regex_pattern}"
                )

        # Choices
        if self.choices is not None and value not in self.choices:
            raise ValueError(
                f"Field '{self.name}': must be one of {self.choices}, got {value!r}"
            )

        # Custom validator
        if self.validator is not None:
            self.validator(value)

        return value

    def __repr__(self):
        parts = [self.field_type.__name__]
        if self.primary_key:
            parts.append("pk")
        if self.required:
            parts.append("required")
        if self.max_length:
            parts.append(f"max={self.max_length}")
        if self.choices:
            parts.append(f"choices={self.choices}")
        return f"Field({', '.join(parts)})"


# Convenience aliases — keep it simple
def IntField(**kwargs):
    return Field(int, **kwargs)

def StrField(**kwargs):
    return Field(str, **kwargs)

def FloatField(**kwargs):
    return Field(float, **kwargs)

def BoolField(**kwargs):
    return Field(bool, **kwargs)

def DateTimeField(**kwargs):
    return Field(datetime, **kwargs)

def TextField(**kwargs):
    return Field(str, **kwargs)

def BlobField(**kwargs):
    return Field(bytes, **kwargs)
