# Tina4 Validator — Request body validation.
"""
Validate request body fields with a consistent API across all Tina4 frameworks.

Usage:
    from tina4_python.validator import Validator

    validator = Validator(request.body)
    validator.required("name", "email")
    validator.email("email")
    validator.min_length("name", 2)
    validator.max_length("name", 100)
    validator.integer("age")
    validator.min("age", 0)
    validator.max("age", 150)
    validator.in_list("role", ["admin", "user", "guest"])
    validator.regex("phone", r"^\\+?[\\d\\s-]+$")

    if not validator.is_valid():
        return response.error("VALIDATION_FAILED", validator.errors()[0]["message"], 400)
"""
import re


class Validator:
    """Request body validator with chainable rules."""

    __slots__ = ("_data", "_errors")

    def __init__(self, data: dict | None = None):
        self._data: dict = data if isinstance(data, dict) else {}
        self._errors: list[dict[str, str]] = []

    # ── Rule methods ──

    def required(self, *fields: str) -> "Validator":
        """Check that one or more fields are present and non-empty."""
        for field in fields:
            value = self._data.get(field)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                self._errors.append({
                    "field": field,
                    "message": f"{field} is required",
                })
        return self

    def email(self, field: str) -> "Validator":
        """Check that a field contains a valid email address."""
        value = self._data.get(field)
        if value is None:
            return self
        if not isinstance(value, str) or not re.match(
            r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", value
        ):
            self._errors.append({
                "field": field,
                "message": f"{field} must be a valid email address",
            })
        return self

    def min_length(self, field: str, length: int) -> "Validator":
        """Check that a string field has at least *length* characters."""
        value = self._data.get(field)
        if value is None:
            return self
        if not isinstance(value, str) or len(value) < length:
            self._errors.append({
                "field": field,
                "message": f"{field} must be at least {length} characters",
            })
        return self

    def max_length(self, field: str, length: int) -> "Validator":
        """Check that a string field has at most *length* characters."""
        value = self._data.get(field)
        if value is None:
            return self
        if not isinstance(value, str) or len(value) > length:
            self._errors.append({
                "field": field,
                "message": f"{field} must be at most {length} characters",
            })
        return self

    def integer(self, field: str) -> "Validator":
        """Check that a field is an integer (or can be parsed as one)."""
        value = self._data.get(field)
        if value is None:
            return self
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            self._errors.append({
                "field": field,
                "message": f"{field} must be an integer",
            })
            return self
        try:
            int(value)
        except (ValueError, TypeError):
            self._errors.append({
                "field": field,
                "message": f"{field} must be an integer",
            })
        return self

    def min(self, field: str, minimum) -> "Validator":
        """Check that a numeric field is >= *minimum*."""
        value = self._data.get(field)
        if value is None:
            return self
        try:
            num = float(value)
        except (ValueError, TypeError):
            return self
        if num < minimum:
            self._errors.append({
                "field": field,
                "message": f"{field} must be at least {minimum}",
            })
        return self

    def max(self, field: str, maximum) -> "Validator":
        """Check that a numeric field is <= *maximum*."""
        value = self._data.get(field)
        if value is None:
            return self
        try:
            num = float(value)
        except (ValueError, TypeError):
            return self
        if num > maximum:
            self._errors.append({
                "field": field,
                "message": f"{field} must be at most {maximum}",
            })
        return self

    def in_list(self, field: str, allowed: list) -> "Validator":
        """Check that a field's value is one of the allowed values."""
        value = self._data.get(field)
        if value is None:
            return self
        if value not in allowed:
            self._errors.append({
                "field": field,
                "message": f"{field} must be one of {allowed}",
            })
        return self

    def regex(self, field: str, pattern: str) -> "Validator":
        """Check that a field matches a regular expression."""
        value = self._data.get(field)
        if value is None:
            return self
        if not isinstance(value, str) or not re.match(pattern, value):
            self._errors.append({
                "field": field,
                "message": f"{field} does not match the required format",
            })
        return self

    # ── Result methods ──

    def errors(self) -> list[dict[str, str]]:
        """Return the list of validation errors (empty if valid)."""
        return list(self._errors)

    def is_valid(self) -> bool:
        """Return True if no validation errors have been recorded."""
        return len(self._errors) == 0
