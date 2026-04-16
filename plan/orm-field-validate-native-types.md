# ORM `Field.validate` — driver-native type coercion bug

**Branch:** `v3` (staging/pre-release). Target release: **3.11.11**.

## Goal

Stop `Field.validate` from crashing the ORM read path when a database driver returns
a native Python type (`datetime`, `Decimal`, `bytes`, `uuid.UUID`, `dict`/`list` for
JSONB, etc.). Keep the existing write-path validation semantics.

## Context

`tina4_python/orm/fields.py:62-70` does an unconditional `self.field_type(value)`
cast. On the ORM read path (`model.py:209` — `field.validate(value)` inside
`_populate`), this calls `datetime(existing_datetime_instance)` for any
`DateTimeField` when the PostgreSQL driver hands back a native `datetime`.
`datetime.__init__` expects an `int` year as its first positional arg, so it
raises `TypeError`, which gets re-wrapped as `ValueError`.

Result: every PostgreSQL read of an ORM row containing a `DateTimeField`
crashes. Same failure mode applies to any field whose `field_type` constructor
doesn't accept its own instance as the sole positional arg.

## Scope across frameworks — dashboard

| Framework   | Field validate re-coerces on read? | Affected? |
|-------------|------------------------------------|-----------|
| tina4-python | ✅ YES — `self.field_type(value)` at fields.py:66 | ✅ BUG — fix required |
| tina4-php    | ❌ NO — `ORM::validate()` returns `[]` stub; casting handled in adapters | ⚪ Not affected |
| tina4-ruby   | ❌ NO — `validate_fields` only checks nullability | ⚪ Not affected |
| tina4-nodejs | ❌ NO — `validate.ts` does type-checks only, no cast | ⚪ Not affected |

Conclusion: the bug is Python-only. Parity fix = Python only, but the expanded
test coverage for driver-native types should be mirrored as a **contract test**
in all four frameworks so regressions are caught early.

## Fix

Handle the three-way split cleanly in `Field.validate`:

1. `BooleanField` + `int` (e.g. SQLite 0/1) → coerce to bool (existing behaviour)
2. `IntegerField` + `bool` → coerce to int (preserve legacy semantics)
3. Value already `isinstance(value, field_type)` → short-circuit (no coercion)
4. Otherwise → try `field_type(value)` as before

Plus: accept strings for `DateTimeField` by routing through
`datetime.fromisoformat(...)` when the driver returns strings (SQLite default).

## Checklist

- [x] Read Python implementation of `Field.validate` and `_populate`
- [x] Confirm PHP/Ruby/Node are not affected (dashboard above)
- [ ] Apply fix in `tina4_python/orm/fields.py`
- [ ] Expand test coverage in `tests/test_orm_fields.py`:
  - [ ] `DateTimeField` accepts native `datetime` round-trip
  - [ ] `DateTimeField` accepts ISO-8601 string (SQLite)
  - [ ] `DateTimeField` with `None` returns default
  - [ ] `BooleanField` still coerces 0/1 → `False`/`True`
  - [ ] `IntegerField` coerces `True` → 1 (legacy)
  - [ ] `IntegerField` short-circuits native int
  - [ ] `BlobField` accepts `bytes` / `memoryview` without re-wrapping
  - [ ] `FloatField` accepts `Decimal` without double-coercion
  - [ ] `StringField` length/regex checks still enforced
- [ ] Run `.venv/bin/python -m pytest tests/test_orm_fields.py -v`
- [ ] Add a parity "contract" test file in php/ruby/node that asserts
      reading a row with a datetime column does not raise
- [ ] Bump to `3.11.11`, tag, push all four frameworks
- [ ] Update `tina4-book` release notes

## Risks / Open questions

- **`bool` is a subclass of `int` in Python** — handled explicitly in the
  branch order so neither direction regresses.
- **Strings to DateTimeField** — `datetime.fromisoformat` covers Python 3.11+
  which is the minimum target. Safe.
- **`None` + `required`** — unchanged path, still raises.
- **Custom `validator` callable** — runs after coercion, unchanged.
