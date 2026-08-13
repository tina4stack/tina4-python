# Feature 19 - Input and request validation: the shared conformance contract.
#
# Replaces the two ``assert True`` PLACEHOLDERS (test_data_validator.py +
# test_form_validator.py) that faked coverage of the request Validator. Parity
# with tina4-nodejs/test/validationContract.test.ts,
# tina4-php/tests/ValidationContractTest.php,
# tina4-ruby/spec/validation_contract_spec.rb.
#
# Two validators, both REAL-tested (no mocks, no doubles):
#   1. the chainable request-body Validator (advisory) - every rule pos + neg;
#   2. ORM field validation, ENFORCED on save() - a constraint-violating model
#      returns False AND writes NOTHING (verified by a real COUNT(*) after, on a
#      real SQLite database);
#   3. both validators speak ONE canonical message vocabulary per rule
#      (VALID-TWO-MESSAGES - Node's request Validator is the reference).
#
# Case names are shared verbatim across the four frameworks and gated by
# tina4-documentation/scripts/audit-contract-fixtures.py.
import pytest

from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database, IntegerField, StringField
from tina4_python.validator import Validator

ROLES = ["admin", "user", "guest"]


class ValidationPerson(ORM):
    table_name = "validation_person"
    id = IntegerField(primary_key=True, auto_increment=True)
    name = StringField(required=True, min_length=2, max_length=5)
    age = IntegerField(min_value=0, max_value=65)
    code = StringField(regex=r"^[0-9]+$")


@pytest.fixture
def vdb(tmp_path):
    """Real SQLite bound to the ORM, with the validation_person table."""
    d = Database(f"sqlite:///{tmp_path / 'validation.db'}")
    d.execute(
        "CREATE TABLE validation_person "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER, code TEXT)"
    )
    d.commit()
    bind_database(d)
    yield d
    d.close()


def _valid_person():
    """A fully valid instance; mutate ONE attribute to make it invalid.

    Attribute assignment stores the value without coercion/raise (unlike the
    constructor, which coerces), so this is how an over-length/out-of-range/
    wrong-format value reaches save() for the enforcement + message checks -
    exactly the "collect, never raise at the boundary" contract.
    """
    return ValidationPerson({"name": "Al", "age": 30, "code": "123"})


# ── 1. request-body Validator: every rule, positive AND negative ─────────────

class TestRequestValidatorRules:
    def test_required_rule_passes_a_present_value_and_reports_a_missing_one(self):
        assert Validator({"name": "Alice"}).required("name").is_valid()
        bad = Validator({"name": ""}).required("name")
        assert not bad.is_valid()
        assert bad.errors()[0]["message"] == "name is required"

    def test_email_rule_passes_a_valid_address_and_reports_an_invalid_one(self):
        assert Validator({"email": "a@b.co"}).email("email").is_valid()
        assert (Validator({"email": "nope"}).email("email").errors()[0]["message"]
                == "email must be a valid email address")

    def test_min_length_rule_passes_a_long_value_and_reports_a_short_one(self):
        assert Validator({"name": "Alice"}).min_length("name", 2).is_valid()
        assert (Validator({"name": "A"}).min_length("name", 2).errors()[0]["message"]
                == "name must be at least 2 characters")

    def test_max_length_rule_passes_a_short_value_and_reports_a_long_one(self):
        assert Validator({"name": "Al"}).max_length("name", 5).is_valid()
        assert (Validator({"name": "Alexander"}).max_length("name", 5).errors()[0]["message"]
                == "name must be at most 5 characters")

    def test_integer_rule_passes_an_integer_and_reports_a_non_integer(self):
        assert Validator({"age": 30}).integer("age").is_valid()
        assert (Validator({"age": "abc"}).integer("age").errors()[0]["message"]
                == "age must be an integer")

    def test_min_rule_passes_a_value_above_the_minimum_and_reports_one_below(self):
        assert Validator({"age": 5}).min("age", 0).is_valid()
        assert (Validator({"age": -5}).min("age", 0).errors()[0]["message"]
                == "age must be at least 0")

    def test_max_rule_passes_a_value_below_the_maximum_and_reports_one_above(self):
        assert Validator({"age": 40}).max("age", 65).is_valid()
        assert (Validator({"age": 999}).max("age", 65).errors()[0]["message"]
                == "age must be at most 65")

    def test_in_list_rule_passes_an_allowed_value_and_reports_a_disallowed_one(self):
        assert Validator({"role": "admin"}).in_list("role", ROLES).is_valid()
        assert (Validator({"role": "root"}).in_list("role", ROLES).errors()[0]["message"]
                == 'role must be one of ["admin","user","guest"]')

    def test_regex_rule_passes_a_matching_value_and_reports_a_non_matching_one(self):
        assert Validator({"code": "123"}).regex("code", r"^[0-9]+$").is_valid()
        assert (Validator({"code": "abc"}).regex("code", r"^[0-9]+$").errors()[0]["message"]
                == "code does not match the required format")

    def test_is_valid_reflects_whether_any_rule_failed(self):
        assert Validator({"name": "Al", "age": 30}).required("name").integer("age").is_valid()
        bad = Validator({"name": "", "age": "x"}).required("name").integer("age")
        assert not bad.is_valid()
        assert len(bad.errors()) == 2


# ── 2. ORM save() ENFORCES field validation and writes NOTHING ───────────────

class TestOrmSaveEnforcement:
    def _count(self, db):
        return db.fetch("SELECT COUNT(*) AS c FROM validation_person").records[0]["c"]

    def test_a_required_violation_makes_save_return_false_and_writes_nothing(self, vdb):
        person = ValidationPerson({"age": 30, "code": "123"})  # name omitted -> None
        assert person.save() is False
        assert self._count(vdb) == 0

    def test_an_over_length_value_makes_save_return_false_and_writes_nothing(self, vdb):
        person = _valid_person()
        person.name = "Alexander"  # 9 chars > max_length 5
        assert person.save() is False
        assert self._count(vdb) == 0

    def test_an_out_of_range_value_makes_save_return_false_and_writes_nothing(self, vdb):
        person = _valid_person()
        person.age = 999  # > max_value 65
        assert person.save() is False
        assert self._count(vdb) == 0

    def test_a_pattern_violation_makes_save_return_false_and_writes_nothing(self, vdb):
        person = _valid_person()
        person.code = "abc"  # fails ^[0-9]+$
        assert person.save() is False
        assert self._count(vdb) == 0

    def test_a_valid_model_saves_and_writes_one_row(self, vdb):
        assert _valid_person().save() is not False
        assert self._count(vdb) == 1


# ── 3. one canonical vocabulary across BOTH validators ───────────────────────

class TestUnifiedMessageVocabulary:
    def test_required_emits_the_same_canonical_message_from_both_validators(self):
        person = ValidationPerson({"age": 30, "code": "123"})  # name None
        req = Validator({}).required("name").errors()[0]["message"]
        assert person.validate()[0] == req == "name is required"

    def test_min_length_emits_the_same_canonical_message_from_both_validators(self):
        person = _valid_person(); person.name = "A"
        req = Validator({"name": "A"}).min_length("name", 2).errors()[0]["message"]
        assert person.validate()[0] == req == "name must be at least 2 characters"

    def test_max_length_emits_the_same_canonical_message_from_both_validators(self):
        person = _valid_person(); person.name = "Alexander"
        req = Validator({"name": "Alexander"}).max_length("name", 5).errors()[0]["message"]
        assert person.validate()[0] == req == "name must be at most 5 characters"

    def test_min_emits_the_same_canonical_message_from_both_validators(self):
        person = _valid_person(); person.age = -5
        req = Validator({"age": -5}).min("age", 0).errors()[0]["message"]
        assert person.validate()[0] == req == "age must be at least 0"

    def test_max_emits_the_same_canonical_message_from_both_validators(self):
        person = _valid_person(); person.age = 999
        req = Validator({"age": 999}).max("age", 65).errors()[0]["message"]
        assert person.validate()[0] == req == "age must be at most 65"

    def test_regex_emits_the_same_canonical_message_from_both_validators(self):
        person = _valid_person(); person.code = "abc"
        req = Validator({"code": "abc"}).regex("code", r"^[0-9]+$").errors()[0]["message"]
        assert person.validate()[0] == req == "code does not match the required format"
