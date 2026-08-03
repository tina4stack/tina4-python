"""queue_contract.json :: an-unsupported-operation-raises-naming-itself

A typo in TINA4_QUEUE_BACKEND must not produce a running app writing every job
to local disk.

MEASURED 2026-08-03: PHP and Node accepted ANY string as a backend name and
silently fell through to the local file store. Python and Ruby already raised -
so this was a two-of-four divergence on a rule the SESSION backend had already
adopted for exactly the same reason.

Python already satisfied both cases and needed no code change. The file exists
anyway, because "correct for a reason we did not choose" is exactly what
regresses silently, and because the shared fixture resolves ONE case name
against EVERY framework's suite.
"""
import pytest

from tina4_python.queue import Queue


class TestQueueBackendValidation:
    def test_an_unknown_queue_backend_raises_instead_of_silently_using_file(self):
        with pytest.raises(ValueError) as excinfo:
            Queue(topic="validation", backend="totally-bogus-backend")

        message = str(excinfo.value)
        # The message must name the offending value AND the valid set, so the
        # operator can fix it without reading the source.
        assert "totally-bogus-backend" in message, message
        for valid in ("file", "rabbitmq", "kafka", "mongodb"):
            assert valid in message, f"the valid set must name {valid!r}: {message}"

    def test_a_queue_backend_name_is_normalised_before_it_is_resolved(self, tmp_path, monkeypatch):
        """' file ' is the same backend as 'file'.

        Without normalisation a stray space in a .env turns a valid
        configuration into the raise above - trading a silent bug for a loud one
        rather than fixing it.
        """
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
        for spelling in (" file ", "FILE", "File", " lite", "DEFAULT"):
            Queue(topic="validation", backend=spelling)  # must not raise

    def test_the_guard_still_accepts_every_documented_backend_name(self, tmp_path, monkeypatch):
        """NEGATIVE: without this, 'make everything raise' would pass the test above."""
        monkeypatch.setenv("TINA4_QUEUE_PATH", str(tmp_path))
        monkeypatch.setenv("TINA4_QUEUE_MONGO_URL", "mongodb://127.0.0.1:27017")
        for spelling in ("mongodb", "mongo", "MongoDB"):
            Queue(topic="validation", backend=spelling)  # must not raise
