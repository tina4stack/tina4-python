"""Parity tests for Python Service base class + register_service shipped
in 3.13.1. Cross-framework parity with PHP Tina4\\Service, Ruby
Tina4::Service, and Node Tina4Service.
"""
from __future__ import annotations

import pytest

from tina4_python.service import Service, ServiceRunner


class _ParityServiceFixture(Service):
    """Concrete Service subclass used as a fixture."""

    def __init__(self):
        super().__init__()
        self.iterations = 0

    def run(self):
        while not self.should_stop():
            self.iterations += 1
            if self.iterations >= 3:
                self.stop()


class TestServiceBaseClass:
    def test_service_class_exists(self):
        assert Service is not None

    def test_run_is_abstract_in_base(self):
        base = Service()
        with pytest.raises(NotImplementedError):
            base.run()

    def test_should_stop_returns_false_initially(self):
        svc = _ParityServiceFixture()
        assert svc.should_stop() is False

    def test_stop_flips_should_stop_to_true(self):
        svc = _ParityServiceFixture()
        svc.stop()
        assert svc.should_stop() is True

    def test_subclass_run_loop_terminates_via_should_stop(self):
        svc = _ParityServiceFixture()
        svc.run()
        assert svc.iterations == 3

    def test_service_is_callable_dispatches_to_run(self):
        svc = _ParityServiceFixture()
        svc()  # __call__ dispatches to run()
        assert svc.iterations == 3


class TestServiceRunnerRegisterService:
    def test_register_service_accepts_service_instance(self):
        runner = ServiceRunner()
        svc = _ParityServiceFixture()
        runner.register_service("parity-test-svc", svc)

        names = [s["name"] for s in runner.services]
        assert "parity-test-svc" in names

    def test_register_service_sets_daemon_true(self):
        runner = ServiceRunner()
        svc = _ParityServiceFixture()
        runner.register_service("daemon-default", svc)

        entry = next(s for s in runner.services if s["name"] == "daemon-default")
        assert entry["daemon"] is True

    def test_register_service_rejects_non_service(self):
        runner = ServiceRunner()
        with pytest.raises(TypeError, match="must be a Service instance"):
            runner.register_service("bad", object())  # not a Service

    def test_register_service_keeps_instance_reference(self):
        runner = ServiceRunner()
        svc = _ParityServiceFixture()
        runner.register_service("with-instance", svc)

        entry = next(s for s in runner.services if s["name"] == "with-instance")
        assert entry["instance"] is svc
        # The handler is the Service itself (callable via __call__)
        assert callable(entry["handler"])

    def test_register_and_register_service_coexist(self):
        runner = ServiceRunner()
        runner.register("function-style", lambda ctx: None, interval=10)
        runner.register_service("class-style", _ParityServiceFixture())

        names = [s["name"] for s in runner.services]
        assert "function-style" in names
        assert "class-style" in names
