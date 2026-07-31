# Tests for TINA4_SESSION_BACKEND name validation.
"""
An unrecognised session backend name must RAISE, not silently become `file`.

The bug these lock in: `Session._resolve_handler` ended in a bare
`else: return FileSessionHandler()`, so any name it did not recognise wrote
sessions to local disk. A typo in TINA4_SESSION_BACKEND ("redsi") or a name that
was valid in one framework but not another produced a running app with sessions
on the wrong storage, nothing logged and nothing failed. The symptom arrived much
later, as users being logged out whenever a request landed on another instance.

NO MOCKS and no dependency: every case here is the pure name -> outcome decision,
asserted through the real Session. Nothing is stubbed, and the cases that would
need a live backend deliberately assert only that the name is not REJECTED,
rather than constructing a connection.

Identical case names in all four frameworks:
  tina4-php/tests/SessionBackendValidationTest.php
  tina4-ruby/spec/session_backend_validation_spec.rb
  tina4-nodejs/test/sessionBackendValidation.test.ts
"""
import os

import pytest

from tina4_python.session import FileSessionHandler, Session


@pytest.fixture(autouse=True)
def _clean_backend_env():
    """Every case owns TINA4_SESSION_BACKEND; restore whatever was there."""
    previous = os.environ.get("TINA4_SESSION_BACKEND")
    os.environ.pop("TINA4_SESSION_BACKEND", None)
    yield
    os.environ.pop("TINA4_SESSION_BACKEND", None)
    if previous is not None:
        os.environ["TINA4_SESSION_BACKEND"] = previous


def test_an_unknown_session_backend_raises_instead_of_silently_using_file():
    """NEGATIVE: the actual bug. This returned a FileSessionHandler before."""
    os.environ["TINA4_SESSION_BACKEND"] = "redsi"

    with pytest.raises(ValueError) as excinfo:
        Session._resolve_handler()

    assert "Unknown session backend" in str(excinfo.value)


def test_the_error_names_the_unknown_backend_and_the_valid_ones():
    os.environ["TINA4_SESSION_BACKEND"] = "postgres"

    with pytest.raises(ValueError) as excinfo:
        Session._resolve_handler()

    message = str(excinfo.value)
    assert "postgres" in message, "the operator cannot see which value was wrong"
    for canonical in Session.CANONICAL_BACKENDS:
        assert canonical in message, f"the message does not offer {canonical}"


def test_an_unset_backend_still_defaults_to_file():
    """POSITIVE: the documented default must survive the new strictness."""
    assert isinstance(Session._resolve_handler(), FileSessionHandler)


def test_a_blank_backend_still_defaults_to_file():
    """
    POSITIVE, and the subtle one. An env var set to "" is a SET variable, so it
    never reaches os.environ.get's default. Treating blank as an unknown name
    would break every deployment that clears the var to take the default.
    """
    os.environ["TINA4_SESSION_BACKEND"] = ""
    assert isinstance(Session._resolve_handler(), FileSessionHandler)

    os.environ["TINA4_SESSION_BACKEND"] = "   "
    assert isinstance(Session._resolve_handler(), FileSessionHandler)


def test_a_backend_name_is_case_and_whitespace_insensitive():
    """A .env line easily carries a trailing space or a capital."""
    for spelling in ("FILE", " file ", "FileSystem", "\tfilesystem\n"):
        os.environ["TINA4_SESSION_BACKEND"] = spelling
        assert isinstance(Session._resolve_handler(), FileSessionHandler), spelling


def test_every_documented_backend_name_is_accepted():
    """
    POSITIVE: the new rejection must not swallow a name that IS valid.

    Only the NAME decision is asserted. Constructing redis/mongo/database would
    reach for a real service, and this case is about validation, so a backend
    that fails to CONNECT still counts as accepted - what must never happen is
    the "Unknown session backend" rejection.
    """
    for name in Session.VALID_BACKENDS:
        os.environ["TINA4_SESSION_BACKEND"] = name
        try:
            Session._resolve_handler()
        except ValueError as err:
            assert "Unknown session backend" not in str(err), (
                f"{name} is in VALID_BACKENDS but the dispatch rejected it"
            )
        except Exception:
            pass  # a connection/driver failure is not a NAME failure


def test_the_canonical_names_are_all_themselves_valid():
    """
    The error message offers CANONICAL_BACKENDS. If one of those were not itself
    accepted, the message would be telling operators to set an invalid value.
    """
    for canonical in Session.CANONICAL_BACKENDS:
        assert canonical in Session.VALID_BACKENDS
