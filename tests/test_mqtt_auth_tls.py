"""MQTT username/password auth and TLS (mqtts://) -- real brokers, no mocks.

Mirrors tina4-ruby spec/mqtt_auth_tls_spec.rb. Broker layout from
plan/v3/spikes/mqtt-infra.sh:

  1883  anonymous
  1884  allow_anonymous false + password_file   -> the auth examples
  8883  TLS, self-signed CA                      -> the mqtts examples

The TLS examples matter more than they look. A TLS suite passes just as happily
with verification switched off, and then "we have TLS" quietly means "we trust
any certificate" -- so the load-bearing assertions are the NEGATIVE ones: a
self-signed cert must be REJECTED when its CA is not supplied, and supplying a CA
for one client must not make a LATER client trust it.
"""
from __future__ import annotations

import os
import socket

import pytest

from tina4_python.mqtt import Mqtt, MqttError

AUTH_URL = os.environ.get("TINA4_TEST_MQTT_AUTH_URL", "mqtt://127.0.0.1:1884")
TLS_URL = os.environ.get("TINA4_TEST_MQTT_TLS_URL", "mqtts://127.0.0.1:8883")
ANON_URL = os.environ.get("TINA4_TEST_MQTT_URL", "mqtt://127.0.0.1:1883")
USERNAME = os.environ.get("TINA4_TEST_MQTT_USERNAME", "tina4")
PASSWORD = os.environ.get("TINA4_TEST_MQTT_PASSWORD", "testpass")


def _ca_file() -> str | None:
    for name in ("TINA4_TEST_MQTT_CA_FILE", "TINA4_MQTT_TEST_CA"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    # Fall back to where mqtt-infra.sh writes its certs by default: its DIR is
    # $TMPDIR/tina4-mqtt-infra, the same location the Ruby helper defaults to, so
    # `sh mqtt-infra.sh && pytest` just works.
    default = os.path.join(os.environ.get("TMPDIR", "/tmp"), "tina4-mqtt-infra", "certs", "ca.crt")
    return os.path.abspath(default) if os.path.isfile(default) else None


def _reachable(url: str) -> bool:
    p = Mqtt.parse_url(url)
    try:
        with socket.create_connection((p["host"], p["port"]), timeout=2):
            return True
    except OSError:
        return False


CA = _ca_file()
auth_broker = pytest.mark.skipif(not _reachable(AUTH_URL), reason=f"auth broker not reachable at {AUTH_URL}")
tls_broker = pytest.mark.skipif(
    not _reachable(TLS_URL) or not CA,
    reason=f"TLS broker not reachable at {TLS_URL} or CA not set (TINA4_TEST_MQTT_CA_FILE)",
)


def _auth_url_with(user: str, pw: str) -> str:
    from urllib.parse import quote
    p = Mqtt.parse_url(AUTH_URL)
    scheme = "mqtts" if p["tls"] else "mqtt"
    creds = ":".join(quote(x, safe="") for x in (user, pw))
    return f"{scheme}://{creds}@{p['host']}:{p['port']}"


@auth_broker
class TestAuth:
    def test_authenticates_with_url_credentials_and_round_trips(self):
        c = Mqtt(url=_auth_url_with(USERNAME, PASSWORD), client_id="tina4-pytest-auth-good", timeout=5)
        assert c.connected and c.username == USERNAME
        topic = "tina4/pytest/authtls/authed"
        assert c.subscribe(topic, qos=1) == 1
        assert isinstance(c.publish(topic, "authenticated", qos=1), int)
        assert c.receive(timeout=3).payload == b"authenticated"
        c.disconnect()

    def test_credentials_as_kwargs(self):
        c = Mqtt(url=AUTH_URL, client_id="tina4-pytest-auth-kw", username=USERNAME, password=PASSWORD, timeout=5)
        assert c.connected
        c.disconnect()

    def test_kwargs_win_over_url(self):
        wrong = _auth_url_with(USERNAME, "definitely-wrong")
        c = Mqtt(url=wrong, client_id="tina4-pytest-auth-override", username=USERNAME, password=PASSWORD, timeout=5)
        assert c.connected
        c.disconnect()

    def test_no_credentials_refused(self):
        with pytest.raises(MqttError) as e:
            Mqtt(url=AUTH_URL, client_id="tina4-pytest-auth-nocreds", timeout=5)
        assert "broker refused the connection" in str(e.value)
        assert "CONNACK return code" in str(e.value)

    def test_wrong_password_refused(self):
        with pytest.raises(MqttError, match=r"CONNACK return code [45]"):
            Mqtt(url=_auth_url_with(USERNAME, "wrong-password"), client_id="tina4-pytest-auth-badpass", timeout=5)

    def test_unknown_username_refused(self):
        with pytest.raises(MqttError, match=r"CONNACK return code [45]"):
            Mqtt(url=_auth_url_with("nobody", PASSWORD), client_id="tina4-pytest-auth-baduser", timeout=5)

    def test_anonymous_listener_accepts_supplied_credentials(self):
        # Credentials the broker does not need must not break the CONNECT payload.
        if not _reachable(ANON_URL):
            pytest.skip("anon broker not reachable")
        c = Mqtt(url=ANON_URL, client_id="tina4-pytest-anon-creds", username=USERNAME, password=PASSWORD, timeout=5)
        assert c.connected
        assert isinstance(c.publish("tina4/pytest/authtls/anon", "fine", qos=1), int)
        c.disconnect()


@tls_broker
class TestTls:
    def test_connects_with_ca_and_negotiates_real_cipher(self):
        c = Mqtt(url=TLS_URL, client_id="tina4-pytest-tls", ca_file=CA, timeout=5)
        assert c.connected and c.tls
        # Not "did it connect" but "is it actually encrypted": a negotiated cipher
        # and a TLS version can only come from a completed handshake.
        assert isinstance(c.cipher, str) and c.cipher
        assert c.tls_version in ("TLSv1.2", "TLSv1.3")
        c.disconnect()

    def test_publish_subscribe_over_tls(self):
        c = Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-rt", ca_file=CA, timeout=5)
        topic = "tina4/pytest/authtls/over-tls"
        assert c.subscribe(topic, qos=1) == 1
        c.publish(topic, "over-tls", qos=1)
        assert c.receive(timeout=5).payload == b"over-tls"
        c.disconnect()

    def test_reassembles_payload_larger_than_one_tls_record(self):
        # A TLS record is at most 16 KB; a 1 MiB payload spans many records AND
        # leaves decrypted bytes buffered inside the TLS layer. A reader that
        # waits on the raw socket while plaintext already sits in the SSL buffer
        # HANGS here -- the pending()-first check in _wait_readable prevents it.
        c = Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-big", ca_file=CA, timeout=10, read_timeout=20)
        topic = "tina4/pytest/authtls/tls-stream"
        c.subscribe(topic, qos=1)
        payload = os.urandom(524_288).hex()  # 1,048,576 chars
        c.publish(topic, payload, qos=1)
        got = c.receive(timeout=20)
        assert len(got.payload) == 1_048_576
        assert got.text() == payload
        c.disconnect()

    def test_rejects_self_signed_when_no_ca_supplied(self):
        # THE test. Everything else about TLS passes identically with verification
        # disabled; only this fails. If it goes green while the positive example
        # also passes, we are not verifying anything.
        with pytest.raises(MqttError) as e:
            Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-noca", timeout=5)
        assert any(s in str(e.value).lower() for s in (
            "certificate verif", "self-signed", "self signed", "unable to get local issuer"))

    def test_no_ca_leak_into_later_client(self):
        # A CA loaded for one client must NOT be trusted by a later client. Each
        # client builds its OWN ssl context/store, so the second still rejects.
        trusted = Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-first", ca_file=CA, timeout=5)
        assert trusted.connected
        with pytest.raises(MqttError):
            Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-second", timeout=5)
        trusted.disconnect()

    def test_reads_ca_from_env(self, monkeypatch):
        monkeypatch.setenv("TINA4_MQTT_CA_FILE", CA)
        c = Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-env", timeout=5)
        assert c.connected
        c.disconnect()

    def test_verify_off_only_when_explicit_and_logs_loudly(self, tmp_path, monkeypatch):
        # Disabling verification is a foot-gun, so it is never the default and it
        # never happens quietly. Asserted against the REAL log FILE the real Log
        # writes (same approach as tina4-ruby and test_log.py) -- capturing
        # stdout/fd is order-fragile because another test may have redirected the
        # Log to a file, so we deterministically point it at our own temp file.
        from tina4_python.debug import Log
        monkeypatch.setenv("TINA4_LOG_OUTPUT", "file")
        Log.configure(log_dir=str(tmp_path), level="warning")
        try:
            insecure = Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-insecure", tls_verify=False, timeout=5)
            assert insecure.connected and insecure.tls
            logged = (tmp_path / "tina4.log").read_text(encoding="utf-8")
            assert "verification is DISABLED" in logged
            assert "man in the middle" in logged
            assert "TINA4_MQTT_CA_FILE" in logged
            insecure.disconnect()
        finally:
            # Reset the shared Log so later tests do not write into the deleted
            # tmp dir (subsequent tests reconfigure it themselves as needed).
            monkeypatch.setenv("TINA4_LOG_OUTPUT", "stdout")
            Log.configure()

    def test_env_verify_flag_is_two_way(self, monkeypatch):
        monkeypatch.setenv("TINA4_MQTT_TLS_VERIFY", "false")
        insecure = Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-envoff", timeout=5)
        assert insecure.connected
        insecure.disconnect()
        # The negative half: the env var must not be a one-way door.
        monkeypatch.setenv("TINA4_MQTT_TLS_VERIFY", "true")
        with pytest.raises(MqttError):
            Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-envon", timeout=5)

    def test_missing_ca_file_reported_by_path(self):
        with pytest.raises(MqttError) as e:
            Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-nofile",
                 ca_file="/nonexistent/tina4-ca.crt", timeout=5)
        assert "/nonexistent/tina4-ca.crt" in str(e.value)
        assert "CA file" in str(e.value)

    def test_auth_and_tls_on_the_same_connection(self):
        if not _reachable(AUTH_URL):
            pytest.skip("auth broker not reachable")
        c = Mqtt(url=TLS_URL, client_id="tina4-pytest-tls-auth",
                 username=USERNAME, password=PASSWORD, ca_file=CA, timeout=5)
        assert c.connected and c.tls
        assert isinstance(c.publish("tina4/pytest/authtls/tls-auth", "both", qos=1), int)
        c.disconnect()
