# Tina4 WSDL — Zero-dependency SOAP 1.1 / WSDL server.
"""
Auto-generates WSDL definitions and handles SOAP XML requests.

    from tina4_python.wsdl import WSDL, wsdl_operation

    class Calculator(WSDL):
        @wsdl_operation({"Result": int})
        def Add(self, a: int, b: int):
            return {"Result": a + b}

    # In a route handler:
    service = Calculator(request)
    return response(service.handle())

Supported:
    - WSDL 1.1 generation from Python type annotations
    - SOAP 1.1 request/response handling
    - Complex types (List[T], Optional[T])
    - Lifecycle hooks (on_request, on_result)
    - Auto type mapping (str, int, float, bool → XSD types)
"""
import re
import inspect
from typing import Any, get_type_hints
from xml.etree import ElementTree as ET


# XSD namespace constants
NS_SOAP = "http://schemas.xmlsoap.org/wsdl/soap/"
NS_WSDL = "http://schemas.xmlsoap.org/wsdl/"
NS_XSD = "http://www.w3.org/2001/XMLSchema"
NS_SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"

_PYTHON_TO_XSD = {
    str: "xsd:string",
    int: "xsd:int",
    float: "xsd:double",
    bool: "xsd:boolean",
    bytes: "xsd:base64Binary",
}


def wsdl_operation(response_schema: dict = None):
    """Decorator to mark a method as a WSDL operation with its response schema."""
    def decorator(func):
        func._wsdl_response = response_schema or {}
        func._is_wsdl_operation = True
        return func
    return decorator


def _xsd_type(python_type) -> str:
    """Map a Python type to an XSD type string."""
    if python_type in _PYTHON_TO_XSD:
        return _PYTHON_TO_XSD[python_type]

    origin = getattr(python_type, "__origin__", None)
    if origin is list:
        return _xsd_type(python_type.__args__[0]) if python_type.__args__ else "xsd:string"

    # Optional[T] = Union[T, None]
    if origin is type(None):
        return "xsd:string"

    args = getattr(python_type, "__args__", None)
    if args and type(None) in args:
        real = [a for a in args if a is not type(None)]
        if real:
            return _xsd_type(real[0])

    return "xsd:string"


def _xsd_type_from_value(value) -> str:
    """Map a Python value's type to XSD."""
    return _PYTHON_TO_XSD.get(type(value), "xsd:string")


class WSDL:
    """SOAP 1.1 service base class.

    Subclass this and decorate methods with @wsdl_operation.
    """

    def __init__(self, request=None, service_url: str = ""):
        self._request = request
        self._service_url = service_url or self._infer_url()
        self._operations = self._discover_operations()

    def _infer_url(self) -> str:
        if self._request and hasattr(self._request, "url"):
            return self._request.url
        return "/"

    def _discover_operations(self) -> dict:
        ops = {}
        for name in dir(self):
            if name.startswith("_"):
                continue
            method = getattr(self, name, None)
            if callable(method) and getattr(method, "_is_wsdl_operation", False):
                ops[name] = method
        return ops

    def handle(self) -> str:
        """Handle a SOAP request or return WSDL on GET/?wsdl."""
        if self._request is None:
            return self.generate_wsdl()

        # Check for WSDL request
        method = "GET"
        if hasattr(self._request, "method"):
            method = getattr(self._request, "method", "GET")
        elif hasattr(self._request, "body") and self._request.body:
            method = "POST"

        params = getattr(self._request, "params", {}) or {}
        url = getattr(self._request, "url", "") or ""

        if method == "GET" or "wsdl" in params or url.endswith("?wsdl"):
            return self.generate_wsdl()

        # Parse SOAP request
        body = ""
        if hasattr(self._request, "body"):
            body = self._request.body if isinstance(self._request.body, str) else str(self._request.body or "")

        return self._process_soap(body)

    def _process_soap(self, xml_body: str) -> str:
        """Parse SOAP XML and invoke the operation."""
        self.on_request(self._request)

        try:
            # Parse XML
            root = ET.fromstring(xml_body)
        except ET.ParseError:
            return self._soap_fault("Client", "Malformed XML")

        # Find the operation element in the SOAP Body
        body_el = None
        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "Body":
                body_el = child
                break

        if body_el is None:
            return self._soap_fault("Client", "Missing SOAP Body")

        # First child of Body is the operation
        op_el = None
        for child in body_el:
            op_el = child
            break

        if op_el is None:
            return self._soap_fault("Client", "Empty SOAP Body")

        op_name = op_el.tag.split("}")[-1] if "}" in op_el.tag else op_el.tag

        if op_name not in self._operations:
            return self._soap_fault("Client", f"Unknown operation: {op_name}")

        method = self._operations[op_name]

        # Extract parameters
        sig = inspect.signature(method)
        hints = get_type_hints(method)
        params = {}
        for param_name in sig.parameters:
            if param_name == "self":
                continue
            # Find matching element
            for child in op_el:
                child_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_name == param_name:
                    value = child.text or ""
                    # Type convert
                    param_type = hints.get(param_name, str)
                    params[param_name] = self._convert_value(value, param_type)
                    break

        try:
            result = method(**params)
            result = self.on_result(result)
        except Exception as e:
            return self._soap_fault("Server", str(e))

        return self._soap_response(op_name, result)

    def _convert_value(self, value: str, target_type) -> Any:
        """Convert a string value to the target Python type."""
        origin = getattr(target_type, "__origin__", None)

        if target_type == int:
            return int(value)
        if target_type == float:
            return float(value)
        if target_type == bool:
            return value.lower() in ("true", "1", "yes")
        if origin is list:
            # Simple comma-separated for now
            inner = target_type.__args__[0] if target_type.__args__ else str
            return [self._convert_value(v.strip(), inner) for v in value.split(",") if v.strip()]

        return value

    def _soap_response(self, op_name: str, result: dict) -> str:
        """Build a SOAP response XML."""
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<soap:Envelope xmlns:soap="{NS_SOAP_ENV}">',
            "<soap:Body>",
            f"<{op_name}Response>",
        ]
        if isinstance(result, dict):
            for k, v in result.items():
                if v is None:
                    parts.append(f"<{k} xsi:nil=\"true\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"/>")
                elif isinstance(v, list):
                    for item in v:
                        parts.append(f"<{k}>{self._escape_xml(str(item))}</{k}>")
                else:
                    parts.append(f"<{k}>{self._escape_xml(str(v))}</{k}>")
        parts.extend([
            f"</{op_name}Response>",
            "</soap:Body>",
            "</soap:Envelope>",
        ])
        return "\n".join(parts)

    def _soap_fault(self, code: str, message: str) -> str:
        """Build a SOAP fault response."""
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<soap:Envelope xmlns:soap="{NS_SOAP_ENV}">'
            f"<soap:Body>"
            f"<soap:Fault>"
            f"<faultcode>{code}</faultcode>"
            f"<faultstring>{self._escape_xml(message)}</faultstring>"
            f"</soap:Fault>"
            f"</soap:Body>"
            f"</soap:Envelope>"
        )

    def generate_wsdl(self) -> str:
        """Generate a WSDL 1.1 definition from the class's operations."""
        service_name = type(self).__name__
        tns = f"urn:{service_name}"

        parts = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<definitions name="{service_name}"',
            f'  targetNamespace="{tns}"',
            f'  xmlns:tns="{tns}"',
            f'  xmlns:soap="{NS_SOAP}"',
            f'  xmlns:xsd="{NS_XSD}"',
            f'  xmlns="{NS_WSDL}">',
            "",
        ]

        # Types
        parts.append("  <types>")
        parts.append(f'    <xsd:schema targetNamespace="{tns}">')

        for op_name, method in self._operations.items():
            hints = get_type_hints(method)
            sig = inspect.signature(method)

            # Request element
            parts.append(f'      <xsd:element name="{op_name}">')
            parts.append("        <xsd:complexType>")
            parts.append("          <xsd:sequence>")
            for pname in sig.parameters:
                if pname == "self":
                    continue
                xsd = _xsd_type(hints.get(pname, str))
                parts.append(f'            <xsd:element name="{pname}" type="{xsd}"/>')
            parts.append("          </xsd:sequence>")
            parts.append("        </xsd:complexType>")
            parts.append(f"      </xsd:element>")

            # Response element
            resp_schema = getattr(method, "_wsdl_response", {})
            parts.append(f'      <xsd:element name="{op_name}Response">')
            parts.append("        <xsd:complexType>")
            parts.append("          <xsd:sequence>")
            for rname, rtype in resp_schema.items():
                xsd = _xsd_type(rtype) if isinstance(rtype, type) else "xsd:string"
                parts.append(f'            <xsd:element name="{rname}" type="{xsd}"/>')
            parts.append("          </xsd:sequence>")
            parts.append("        </xsd:complexType>")
            parts.append(f"      </xsd:element>")

        parts.append("    </xsd:schema>")
        parts.append("  </types>")
        parts.append("")

        # Messages
        for op_name in self._operations:
            parts.append(f'  <message name="{op_name}Input">')
            parts.append(f'    <part name="parameters" element="tns:{op_name}"/>')
            parts.append("  </message>")
            parts.append(f'  <message name="{op_name}Output">')
            parts.append(f'    <part name="parameters" element="tns:{op_name}Response"/>')
            parts.append("  </message>")
        parts.append("")

        # PortType
        parts.append(f'  <portType name="{service_name}PortType">')
        for op_name in self._operations:
            parts.append(f'    <operation name="{op_name}">')
            parts.append(f'      <input message="tns:{op_name}Input"/>')
            parts.append(f'      <output message="tns:{op_name}Output"/>')
            parts.append("    </operation>")
        parts.append("  </portType>")
        parts.append("")

        # Binding
        parts.append(f'  <binding name="{service_name}Binding" type="tns:{service_name}PortType">')
        parts.append(f'    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>')
        for op_name in self._operations:
            parts.append(f'    <operation name="{op_name}">')
            parts.append(f'      <soap:operation soapAction="{tns}/{op_name}"/>')
            parts.append("      <input><soap:body use=\"literal\"/></input>")
            parts.append("      <output><soap:body use=\"literal\"/></output>")
            parts.append("    </operation>")
        parts.append("  </binding>")
        parts.append("")

        # Service
        parts.append(f'  <service name="{service_name}">')
        parts.append(f'    <port name="{service_name}Port" binding="tns:{service_name}Binding">')
        parts.append(f'      <soap:address location="{self._service_url}"/>')
        parts.append("    </port>")
        parts.append("  </service>")

        parts.append("</definitions>")
        return "\n".join(parts)

    def on_request(self, request):
        """Hook: called before operation invocation. Override to validate/log."""
        pass

    def on_result(self, result):
        """Hook: called after operation returns. Override to transform/audit."""
        return result

    @staticmethod
    def _escape_xml(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


__all__ = ["WSDL", "wsdl_operation"]
