"""Tests for host/port configuration resolution.

Priority: CLI flag > ENV var > default (0.0.0.0:7145)
"""
import os
import pytest

from tina4_python.core.server import resolve_config


class TestDefaults:
    """Default values when no CLI flags or ENV vars are set."""

    def test_default_port(self, monkeypatch):
        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.delenv("HOST", raising=False)
        _, port = resolve_config()
        assert port == 7145

    def test_default_host(self, monkeypatch):
        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.delenv("HOST", raising=False)
        host, _ = resolve_config()
        assert host == "0.0.0.0"


class TestEnvVars:
    """ENV vars override defaults."""

    def test_port_env(self, monkeypatch):
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.delenv("HOST", raising=False)
        _, port = resolve_config()
        assert port == 9000

    def test_host_env(self, monkeypatch):
        monkeypatch.setenv("HOST", "127.0.0.1")
        monkeypatch.delenv("PORT", raising=False)
        host, _ = resolve_config()
        assert host == "127.0.0.1"

    def test_port_env_non_numeric_ignored(self, monkeypatch):
        monkeypatch.setenv("PORT", "not-a-number")
        _, port = resolve_config()
        assert port == 7145

    def test_both_env_vars(self, monkeypatch):
        monkeypatch.setenv("HOST", "10.0.0.1")
        monkeypatch.setenv("PORT", "3000")
        host, port = resolve_config()
        assert host == "10.0.0.1"
        assert port == 3000


class TestCliOverridesEnv:
    """CLI flags take priority over ENV vars."""

    def test_cli_port_overrides_env(self, monkeypatch):
        monkeypatch.setenv("PORT", "9000")
        _, port = resolve_config(cli_port=8080)
        assert port == 8080

    def test_cli_host_overrides_env(self, monkeypatch):
        monkeypatch.setenv("HOST", "10.0.0.1")
        host, _ = resolve_config(cli_host="192.168.1.1")
        assert host == "192.168.1.1"

    def test_cli_overrides_both(self, monkeypatch):
        monkeypatch.setenv("HOST", "10.0.0.1")
        monkeypatch.setenv("PORT", "9000")
        host, port = resolve_config(cli_host="0.0.0.0", cli_port=4000)
        assert host == "0.0.0.0"
        assert port == 4000

    def test_cli_port_only_env_host_used(self, monkeypatch):
        monkeypatch.setenv("HOST", "10.0.0.1")
        monkeypatch.delenv("PORT", raising=False)
        host, port = resolve_config(cli_port=5555)
        assert host == "10.0.0.1"
        assert port == 5555

    def test_cli_host_only_env_port_used(self, monkeypatch):
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.delenv("HOST", raising=False)
        host, port = resolve_config(cli_host="localhost")
        assert host == "localhost"
        assert port == 9000
