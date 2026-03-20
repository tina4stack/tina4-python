# Tests for tina4_python.wsdl
import pytest
from tina4_python.wsdl import WSDL, wsdl_operation


# ── Test service ──────────────────────────────────────────────

class Calculator(WSDL):
    @wsdl_operation({"Result": int})
    def Add(self, a: int, b: int):
        return {"Result": a + b}

    @wsdl_operation({"Result": float})
    def Divide(self, a: float, b: float):
        if b == 0:
            raise ValueError("Division by zero")
        return {"Result": a / b}

    @wsdl_operation({"Greeting": str})
    def Greet(self, name: str):
        return {"Greeting": f"Hello, {name}!"}


class HookedService(WSDL):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request_logged = False
        self.result_modified = False

    @wsdl_operation({"Value": int})
    def Echo(self, value: int):
        return {"Value": value}

    def on_request(self, request):
        self.request_logged = True

    def on_result(self, result):
        self.result_modified = True
        return result


# ── WSDL Generation ──────────────────────────────────────────


class TestWSDLGeneration:
    def test_generates_valid_wsdl(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert '<?xml version="1.0"' in wsdl
        assert "<definitions" in wsdl
        assert "Calculator" in wsdl

    def test_contains_operations(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "Add" in wsdl
        assert "Divide" in wsdl
        assert "Greet" in wsdl

    def test_contains_messages(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "AddInput" in wsdl
        assert "AddOutput" in wsdl

    def test_contains_binding(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "CalculatorBinding" in wsdl
        assert "soap:binding" in wsdl

    def test_contains_service(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert '<service name="Calculator">' in wsdl
        assert "soap:address" in wsdl

    def test_parameter_types(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert 'type="xsd:int"' in wsdl
        assert 'type="xsd:double"' in wsdl
        assert 'type="xsd:string"' in wsdl

    def test_response_types(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "AddResponse" in wsdl
        assert "DivideResponse" in wsdl


# ── SOAP Request Handling ────────────────────────────────────


class TestSOAPHandling:
    def _soap_request(self, op_name, params_xml):
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f'<soap:Body>'
            f'<{op_name}>{params_xml}</{op_name}>'
            f'</soap:Body>'
            f'</soap:Envelope>'
        )

    def test_add_operation(self):
        req = type("R", (), {"body": self._soap_request("Add", "<a>5</a><b>3</b>"), "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "<Result>8</Result>" in result
        assert "AddResponse" in result

    def test_greet_operation(self):
        req = type("R", (), {"body": self._soap_request("Greet", "<name>World</name>"), "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "Hello, World!" in result

    def test_unknown_operation(self):
        req = type("R", (), {"body": self._soap_request("Unknown", ""), "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "faultcode" in result
        assert "Unknown operation" in result

    def test_malformed_xml(self):
        req = type("R", (), {"body": "not xml at all", "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "faultcode" in result
        assert "Malformed XML" in result

    def test_server_error(self):
        req = type("R", (), {"body": self._soap_request("Divide", "<a>10</a><b>0</b>"), "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "faultcode" in result
        assert "Division by zero" in result

    def test_wsdl_on_get(self):
        req = type("R", (), {"url": "/?wsdl", "params": {"wsdl": ""}, "method": "GET"})()
        calc = Calculator(req)
        result = calc.handle()
        assert "<definitions" in result


# ── Lifecycle Hooks ──────────────────────────────────────────


class TestLifecycleHooks:
    def test_on_request_called(self):
        req = type("R", (), {
            "body": (
                '<?xml version="1.0"?>'
                '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                '<soap:Body><Echo><value>42</value></Echo></soap:Body>'
                '</soap:Envelope>'
            ),
            "url": "/svc", "params": {},
        })()
        svc = HookedService(req)
        svc.handle()
        assert svc.request_logged

    def test_on_result_called(self):
        req = type("R", (), {
            "body": (
                '<?xml version="1.0"?>'
                '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                '<soap:Body><Echo><value>42</value></Echo></soap:Body>'
                '</soap:Envelope>'
            ),
            "url": "/svc", "params": {},
        })()
        svc = HookedService(req)
        svc.handle()
        assert svc.result_modified


# ── Decorator ─────────────────────────────────────────────────


class TestDecorator:
    def test_marks_function(self):
        @wsdl_operation({"Out": str})
        def my_op(self, x: str):
            return {"Out": x}

        assert my_op._is_wsdl_operation is True
        assert my_op._wsdl_response == {"Out": str}

    def test_empty_response(self):
        @wsdl_operation()
        def void_op(self):
            return {}

        assert void_op._wsdl_response == {}
