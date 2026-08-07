"""Messenger SEND-SIGNATURE contract, mirroring tina4-nodejs#41 and #42.

This is the send()/capture() signature-and-branch contract (one name = one
signature; the factory returns one concrete type; cc/bcc normalise at the
boundary). It is SEPARATE from the IMAP read-path contract in
tests/test_messenger_contract.py, which pins the 14 invariants of
plan/v3/fixtures/messenger_contract.json. Both must hold.

Four contract points, each with a POSITIVE test (the right behaviour is accepted)
and a NEGATIVE test (the wrong behaviour is rejected). The same eight run in all
four frameworks. Contract and the ADR-0004 ranking:
tina4-documentation/plan/v3/messenger-contract.md.

Python looked like the least broken of the four until the code was actually run.
It is not. ``create_messenger()`` installs the dev path by assigning over the
instance method (``messenger.send = dev_send``), and ``dev_send`` is declared

    (to, subject, body, html=False, cc=None, ...)

while the class declares

    (to, subject, body, html=False, text=None, cc=None, ...)

Two different signatures behind one name, which produces three failures at once:

* ``send(to, subj, body, True, "plain text")`` files the plain-text body as a CC
  RECIPIENT and returns success. That is nodejs#42, in Python.
* ``send(..., text="plain text")`` raises ``TypeError`` -- the keyword the class
  documents does not exist on the object you were handed.
* ``capture()`` normalises nothing, so a caller reaching it directly with a
  bare-string ``cc`` stores a malformed message and is told it succeeded.

What Python does get right, and what the contract keeps: the factory returns ONE
type (so #41 cannot happen), and the dev path normalises cc/bcc from a bare string
to a list. The fix moves that normalisation into ``capture()`` and replaces the
swap with a real branch inside ``Messenger.send()``.

The dev-capture gate is ``TINA4_DEBUG`` truthy OR no SMTP host configured (see the
contract, point 3), so the fixture sets TINA4_DEBUG and clears TINA4_MAIL_HOST --
both conditions, the state of any dev box.

NO MOCKS: DevMailbox writes real JSON. Each test points TINA4_MAILBOX_DIR at a
tmp_path and reads the file back off disk.
"""
import inspect
import json
from pathlib import Path

import pytest

from tina4_python.messenger import Messenger, create_messenger


def _captured(mailbox_dir: Path) -> dict:
    """The captured message, read off disk.

    Globs recursively rather than assuming a folder name: the four frameworks lay
    the mailbox out differently and these assertions are about content.
    """
    files = sorted(mailbox_dir.rglob("*.json"))
    assert len(files) >= 1, f"nothing captured under {mailbox_dir}"
    return json.loads(files[0].read_text())


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    """Isolated real mailbox, with the dev path active per the contract's gate."""
    monkeypatch.setenv("TINA4_MAILBOX_DIR", str(tmp_path))
    monkeypatch.setenv("TINA4_DEBUG", "true")
    monkeypatch.delenv("TINA4_MAIL_HOST", raising=False)
    return tmp_path


# --- 1. the factory returns ONE type, and it can send -----------------------

def test_positive_factory_returns_a_sender(mailbox):
    mail = create_messenger()
    assert callable(getattr(mail, "send", None)), (
        f"create_messenger() returned {type(mail).__name__} with no callable send()"
    )


def test_negative_factory_never_returns_a_capture_only_object(mailbox):
    """The #41 failure mode: a returned object whose only sending verb is capture()."""
    mail = create_messenger()
    has_send = callable(getattr(mail, "send", None))
    has_only_capture = callable(getattr(mail, "capture", None)) and not has_send
    assert not has_only_capture, (
        f"create_messenger() returned {type(mail).__name__}, which offers capture() "
        "but not send(). Callers holding the factory result cannot send without "
        "branching on the concrete type."
    )


# --- 2. text is the 5th argument and lands in text --------------------------

def test_positive_text_round_trips(mailbox):
    mail = create_messenger()
    mail.send("a@b.com", "Subj", "<p>body</p>", True, "the text part")
    msg = _captured(mailbox)
    assert "text" in msg, (
        "the captured message has no text field at all, so it is not what would "
        "have been sent"
    )
    assert msg["text"] == "the text part"


def test_negative_text_is_never_stored_as_a_cc_recipient(mailbox):
    """The #42 failure mode, stated as the thing that must NOT happen."""
    mail = create_messenger()
    mail.send("a@b.com", "Subject", "<p>hi</p>", True, "plain text alternative")
    msg = _captured(mailbox)
    cc = msg.get("cc") or []
    assert "plain text alternative" not in (cc if isinstance(cc, list) else [cc]), (
        f"the plain-text body was filed as a CC recipient: cc={cc!r}"
    )


# --- 3. cc/bcc are normalised at the boundary ------------------------------

def test_positive_a_proper_cc_list_passes_through_unchanged(mailbox):
    mail = create_messenger()
    mail.send("a@b.com", "S", "<p>b</p>", True, None, ["x@y.com", "p@q.com"])
    msg = _captured(mailbox)
    assert msg.get("cc") == ["x@y.com", "p@q.com"], (
        f"a valid cc list was altered: {msg.get('cc')!r}"
    )


def test_negative_a_bare_string_cc_is_not_stored_as_a_bare_string(mailbox):
    """A dev mailbox that accepts a malformed message and reports success defeats
    its own purpose: it exists to show you what you would have sent.

    Goes through send(), not capture(). The contract makes capture() internal, so
    the boundary that must normalise is the public one -- and normalising in one
    caller (Python does it in dev_send, not in capture) means the same message is
    well-formed or malformed depending on which door it came through.
    """
    mail = create_messenger()
    mail.send("a@b.com", "Subject", "<p>hi</p>", True, None, "one@cc.com")
    msg = _captured(mailbox)
    assert not isinstance(msg.get("cc"), str), (
        f"cc was stored as a bare string where a list is declared: {msg.get('cc')!r}"
    )
    assert msg.get("cc") == ["one@cc.com"]


# --- 4. interception is a branch, not a method swap ------------------------

def test_positive_send_is_the_class_method(mailbox):
    """After the fix, the dev path is a branch INSIDE send(), so the instance uses
    the class's method and the two never disagree."""
    mail = create_messenger()
    assert getattr(mail, "send").__func__ is Messenger.send, (
        "the instance's send() is not the class's send(); interception is still "
        "installed by assigning over the method"
    )


def test_negative_send_does_not_have_a_different_signature_than_the_class(mailbox):
    """The swap's real cost, and why 'it works positionally' is not good enough.

    A caller reads Messenger.send's signature and writes send(..., text=...). On a
    dev messenger that raises TypeError, because the object's send is a different
    function with different parameters. One name must mean one signature.
    """
    mail = create_messenger()
    assert "send" not in vars(mail), (
        "send was found in the instance __dict__, so it has been assigned over. "
        "Interception must be a real branch inside Messenger.send()."
    )
    assert inspect.signature(mail.send) == inspect.signature(
        Messenger.send
    ).replace(
        parameters=[
            p for name, p in inspect.signature(Messenger.send).parameters.items()
            if name != "self"
        ]
    ), (
        f"the object's send{inspect.signature(mail.send)} does not match the class's "
        f"send{inspect.signature(Messenger.send)} -- callers cannot trust the "
        "documented keywords"
    )
