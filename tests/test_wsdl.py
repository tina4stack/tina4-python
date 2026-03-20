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


# ── WSDL Generation Extra ────────────────────────────────────


class TestWSDLGenerationExtra:
    def test_xml_declaration(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert wsdl.startswith('<?xml version="1.0"')

    def test_target_namespace(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "urn:Calculator" in wsdl

    def test_contains_types_section(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "<types>" in wsdl
        assert "<xsd:schema" in wsdl

    def test_contains_port_type(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "CalculatorPortType" in wsdl

    def test_contains_port(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "CalculatorPort" in wsdl

    def test_soap_operation_action(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "soapAction" in wsdl

    def test_document_style(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert 'style="document"' in wsdl

    def test_literal_use(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert 'use="literal"' in wsdl

    def test_input_output_messages(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert "DivideInput" in wsdl
        assert "DivideOutput" in wsdl
        assert "GreetInput" in wsdl
        assert "GreetOutput" in wsdl

    def test_parameter_names_in_wsdl(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert 'name="a"' in wsdl
        assert 'name="b"' in wsdl
        assert 'name="name"' in wsdl


# ── SOAP Request Handling Extra ──────────────────────────────


class TestSOAPHandlingExtra:
    def _soap_request(self, op_name, params_xml):
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f'<soap:Body>'
            f'<{op_name}>{params_xml}</{op_name}>'
            f'</soap:Body>'
            f'</soap:Envelope>'
        )

    def test_divide_operation(self):
        req = type("R", (), {"body": self._soap_request("Divide", "<a>10</a><b>2</b>"), "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "<Result>5.0</Result>" in result
        assert "DivideResponse" in result

    def test_response_is_xml(self):
        req = type("R", (), {"body": self._soap_request("Add", "<a>1</a><b>2</b>"), "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert '<?xml' in result

    def test_response_contains_envelope(self):
        req = type("R", (), {"body": self._soap_request("Add", "<a>1</a><b>2</b>"), "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "Envelope" in result
        assert "Body" in result

    def test_empty_body_element(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            '<soap:Body></soap:Body>'
            '</soap:Envelope>'
        )
        req = type("R", (), {"body": xml, "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "faultcode" in result

    def test_missing_body_element(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            '</soap:Envelope>'
        )
        req = type("R", (), {"body": xml, "url": "/calc", "params": {}})()
        calc = Calculator(req)
        result = calc.handle()
        assert "faultcode" in result
        assert "Missing SOAP Body" in result or "Body" in result


# ── Type Mapping ─────────────────────────────────────────────


class TestTypeMapping:
    def test_bool_type(self):
        from tina4_python.wsdl import _xsd_type
        assert _xsd_type(bool) == "xsd:boolean"

    def test_bytes_type(self):
        from tina4_python.wsdl import _xsd_type
        assert _xsd_type(bytes) == "xsd:base64Binary"

    def test_int_type(self):
        from tina4_python.wsdl import _xsd_type
        assert _xsd_type(int) == "xsd:int"

    def test_float_type(self):
        from tina4_python.wsdl import _xsd_type
        assert _xsd_type(float) == "xsd:double"

    def test_str_type(self):
        from tina4_python.wsdl import _xsd_type
        assert _xsd_type(str) == "xsd:string"

    def test_unknown_type_defaults_to_string(self):
        from tina4_python.wsdl import _xsd_type
        assert _xsd_type(object) == "xsd:string"

    def test_value_type_mapping_string(self):
        from tina4_python.wsdl import _xsd_type_from_value
        assert _xsd_type_from_value("hello") == "xsd:string"

    def test_value_type_mapping_int(self):
        from tina4_python.wsdl import _xsd_type_from_value
        assert _xsd_type_from_value(42) == "xsd:int"

    def test_value_type_mapping_float(self):
        from tina4_python.wsdl import _xsd_type_from_value
        assert _xsd_type_from_value(3.14) == "xsd:double"

    def test_value_type_mapping_bool(self):
        from tina4_python.wsdl import _xsd_type_from_value
        assert _xsd_type_from_value(True) == "xsd:boolean"


# ── Value Conversion ─────────────────────────────────────────


class TestValueConversion:
    def test_convert_int(self):
        calc = Calculator()
        assert calc._convert_value("42", int) == 42

    def test_convert_float(self):
        calc = Calculator()
        assert calc._convert_value("3.14", float) == 3.14

    def test_convert_bool_true(self):
        calc = Calculator()
        assert calc._convert_value("true", bool) is True

    def test_convert_bool_yes(self):
        calc = Calculator()
        assert calc._convert_value("yes", bool) is True

    def test_convert_bool_1(self):
        calc = Calculator()
        assert calc._convert_value("1", bool) is True

    def test_convert_bool_false(self):
        calc = Calculator()
        assert calc._convert_value("false", bool) is False

    def test_convert_string(self):
        calc = Calculator()
        assert calc._convert_value("hello", str) == "hello"


# ── XML Escaping ─────────────────────────────────────────────


class TestXMLEscaping:
    def test_escape_ampersand(self):
        from tina4_python.wsdl import WSDL
        assert WSDL._escape_xml("a&b") == "a&amp;b"

    def test_escape_less_than(self):
        from tina4_python.wsdl import WSDL
        assert WSDL._escape_xml("a<b") == "a&lt;b"

    def test_escape_greater_than(self):
        from tina4_python.wsdl import WSDL
        assert WSDL._escape_xml("a>b") == "a&gt;b"

    def test_escape_quote(self):
        from tina4_python.wsdl import WSDL
        assert WSDL._escape_xml('a"b') == "a&quot;b"

    def test_escape_plain_text(self):
        from tina4_python.wsdl import WSDL
        assert WSDL._escape_xml("hello world") == "hello world"


# ── Service with Different Type ──────────────────────────────


class StringService(WSDL):
    @wsdl_operation({"Greeting": str})
    def Greet(self, name: str):
        return {"Greeting": f"Hello, {name}!"}


class TestStringService:
    def test_string_wsdl_has_xsd_string(self):
        svc = StringService()
        wsdl = svc.generate_wsdl()
        assert 'type="xsd:string"' in wsdl

    def test_string_operation(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            '<soap:Body><Greet><name>World</name></Greet></soap:Body>'
            '</soap:Envelope>'
        )
        req = type("R", (), {"body": xml, "url": "/svc", "params": {}})()
        svc = StringService(req)
        result = svc.handle()
        assert "Hello, World!" in result
        assert "GreetResponse" in result


# ── WSDL Default Endpoint ────────────────────────────────────


class TestWSDLEndpoint:
    def test_default_url_from_request(self):
        req = type("R", (), {"url": "/my-service", "params": {}})()
        calc = Calculator(req)
        wsdl = calc.generate_wsdl()
        assert 'location="/my-service"' in wsdl

    def test_explicit_service_url(self):
        calc = Calculator(service_url="http://localhost:3000/api/calculator")
        wsdl = calc.generate_wsdl()
        assert 'location="http://localhost:3000/api/calculator"' in wsdl

    def test_no_request_defaults_to_slash(self):
        calc = Calculator()
        wsdl = calc.generate_wsdl()
        assert 'location="/"' in wsdl
