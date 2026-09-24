# Task: ORM field column read-back (Field(column=) round-trips on every read path)

**Outcome:** one attribute->column resolver (`ORM.get_db_column`: `field_mapping`, then
`Field.column`, then the name) drives every ORM read and write path, and hydration reverses
it. `name = StringField(column="full_name")` reads back into `name` through find / all /
where / select / load / relationships / GraphQL / seeder, with no stray `full_name` attribute.

## Scope
- [x] Reproduce on origin/v3, real SQLite, PostgreSQL, MySQL, MSSQL, Firebird: 65 of 75 red
- [x] `_populate()` reverses `get_db_column` (`_column_to_attribute()`)
- [x] `_get_db_column()` delegates to `get_db_column()`; `_attribute_for()` added (reverse)
- [x] find({...}) filter, soft-delete column, PK / insert / update / create_table sites
- [x] Relationship SQL: lazy has_one / has_many, eager has_* / belongs_to, imperative has_one / has_many / belongs_to
- [x] GraphQL from_orm resolvers address the row by the key COLUMN
- [x] Seeder FK pool reads the parent's key COLUMN
- [x] Found on the way, fixed: PostgreSQL last_id for a key not named "id"; lazy has_one "LIMIT 1" (MSSQL/Firebird syntax error); MySQL fetch_one leaving unread rows
- [x] Full suite: lab 6197 passed / 0 failed / 37 skipped (all [needs:graph]); local macOS 6185 passed, 12 env-only failures (MQTT TLS CA, local Mongo) that are green on the lab

## Parity
| Path | Python | PHP | Ruby | Node |
|------|--------|-----|------|------|
| per-field column option | `Field(column=)` | none | none | none |
| field_mapping read-back | fixed | already correct (lock-in test) | fixed (find pk, pk_filter, relationships) | fixed (insert key on MySQL/MSSQL/Firebird) |

## Tests (written first, real, no mocks, positive + negative)
- [x] tests/test_orm_field_column_readback.py: 19 cases x 5 engines + 1 PostgreSQL case = 96, all green; 65 red on origin/v3
- [x] Mutation-proved: 17 fix sites each turn the file red when reverted

## Bugs
- [x] Field(column=) value hydrates onto a stray attribute, declared field stays None
- [x] `_get_db_column()` ignores Field.column
- [x] `find({"attr": v})` filters on the attribute name, not the column
- [x] soft-delete flag ignores `is_deleted = Field(column=...)`
- [x] relationship SQL uses the FK / PK attribute name as the column
- [x] GraphQL from_orm single / update / delete query the PK attribute name
- [x] seeder FK pool selects the PK attribute name
- [x] PostgreSQL: save() leaves an auto-increment key not named "id" as None (RETURNING read only "id"); lastval() fallback guarded against a stale value
- [x] lazy has_one appended "LIMIT 1" (syntax error on MSSQL and Firebird)
- [x] MySQL fetch_one on a multi-row result left rows unread ("Unread result found" on the next statement, then a metadata lock)

## Commits
- af55604  ORM reads a Field(column=) back through one column resolver (rebased onto fix/identifier-allow-list, #148)

## Status: Complete
