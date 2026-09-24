"""An MQTT URL that fails to parse never puts its password in the error.

THE BUG, MEASURED on v3 (13464d4): ``Mqtt.parse_url`` built four of its
ValueError messages from the raw URL (``{raw!r}``), so a typo in the port of
``mqtt://tina4:s3ntinel-pw@broker:18a3`` raised an error - which lands in a log
or a traceback - carrying ``s3ntinel-pw``. The fix routes the URL through
``redact_url``, the framework's single redaction primitive.

Pure logic: parse_url is a function over its input with no dependency, so no
service and no double is involved.
"""
import pytest

from tina4_python.mqtt import Mqtt

PASSWORD = "s3ntinel-pw"

MALFORMED_URLS_WITH_A_PASSWORD = [
    # unsupported scheme
    f"ws://tina4:{PASSWORD}@broker.example:1883",
    # unclosed IPv6 bracket
    f"mqtt://tina4:{PASSWORD}@[::1:1883",
    # no host after the credentials
    f"mqtt://tina4:{PASSWORD}@:1883",
    # non-numeric port
    f"mqtt://tina4:{PASSWORD}@broker.example:18a3",
]


@pytest.mark.parametrize("url", MALFORMED_URLS_WITH_A_PASSWORD)
def test_parse_error_never_contains_the_password(url):
    with pytest.raises(ValueError) as raised:
        Mqtt.parse_url(url)
    message = str(raised.value)
    assert PASSWORD not in message, message
    # Still useful: the user, the scheme and the redaction marker are shown.
    assert "tina4:***@" in message, message


def test_a_valid_url_still_parses_its_password():
    """Positive control: redaction is only in the MESSAGE, never the value used."""
    parsed = Mqtt.parse_url(f"mqtt://tina4:{PASSWORD}@broker.example:1883")
    assert parsed["password"] == PASSWORD
    assert parsed["host"] == "broker.example"
    assert parsed["port"] == 1883
