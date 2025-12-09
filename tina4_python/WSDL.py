#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""
Tina4 Python – Built-in SOAP 1.1 / WSDL 1.0 Service
===================================================

Zero-configuration SOAP web service with automatic WSDL generation.
Works seamlessly with Tina4 routing and respects reverse proxies.

Features:
    • Auto-generates full WSDL on ?wsdl
    • Document/literal wrapped style
    • Full support for str, int, float, bool, List[T], Optional[T]
    • Automatic ArrayOfX complex types
    • Proper xsi:nil handling
    • X-Forwarded-* header support
    • Optional hooks: on_request / on_result
    • Optional static SERVICE_URL override

Usage example at the bottom of this file.
"""

from typing import get_origin, get_args, List, Optional, Dict, Any
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, QName
import inspect


# --------------------------------------------------------------
# Decorator: declare exact response structure
# --------------------------------------------------------------
def wsdl_operation(return_schema: dict):
    """
    Declare the exact structure of the SOAP response for a method.

    Example:
        @wsdl_operation({
            "SessionId": str,
            "Expires": str,
            "Roles": List[str],
            "Error": Optional[str]
        })
        def Login(self, Username: str, Password: str):
            ...

    Supported types:
        str, int, float, bool
        List[T], list[T]           → generates <ArrayOfX> complex type
        Optional[T]                → minOccurs="0" + nillable="true"
    """
    def decorator(func):
        func._wsdl_return_schema = return_schema
        return func
    return decorator


# --------------------------------------------------------------
# Main WSDL Class – Fixed & Complete
# --------------------------------------------------------------
class WSDL:
    """
    Turn any class into a full SOAP 1.1 web service with auto-generated WSDL.

    Instantiate with a Tina4 request object and return the result of .handle().
    """

    # Basic XSD type mapping – can be extended in subclasses if needed
    XSD_TYPES = {
        str: "xsd:string",
        int: "xsd:integer",
        float: "xsd:double",
        bool: "xsd:boolean",
    }

    # Optional class-level override for the service endpoint (useful behind proxies)
    SERVICE_URL: str = None

    def __init__(self, request):
        self.request = request
        self._array_types = set()

    def _convert_param(self, value, annotation):
        """Auto-convert incoming SOAP strings to proper Python types"""
        origin = get_origin(annotation)
        args = get_args(annotation)

        if origin in (list, List):
            item_type = args[0] if args else str
            return [self._convert_param(v, item_type) for v in (value or []) if v is not None]
        if annotation == int and isinstance(value, str):
            return int(value)
        if annotation == float and isinstance(value, str):
            return float(value)
        if annotation == bool and isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return value

    # ------------------------------------------------------------------
    # Discover public SOAP operations (methods that should become operations)
    # ------------------------------------------------------------------
    def get_operations(self) -> List[str]:
        """Return list of callable public methods that are not excluded."""
        excluded = {
            '__init__', 'handle', 'generate_wsdl', 'soap_fault',
            'get_operations', 'on_request', 'on_result'
        }
        return [
            name for name in dir(self)
            if callable(getattr(self, name))
               and not name.startswith('_')
               and name not in excluded
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _xsd_type(self, py_type) -> str:
        """Convert a Python type (including generics) to an XSD type string."""
        origin = get_origin(py_type)
        args = get_args(py_type)

        # Optional[T] → T (but keep minOccurs=0 later)
        if origin is Optional:
            py_type = args[0] if args else str

        if py_type in self.XSD_TYPES:
            return self.XSD_TYPES[py_type]
        return "xsd:string"  # safe fallback

    def _register_array_type(self, schema_elem: Element, item_py_type) -> str:
        """
        Register an ArrayOfX complex type if not already done.
        Returns the qualified type name, e.g. tns:ArrayOfString
        """
        item_xsd = self._xsd_type(item_py_type)
        base = item_xsd.split(":")[-1].capitalize()  # string → String
        array_name = f"ArrayOf{base}"

        if array_name in self._array_types:
            return f"tns:{array_name}"

        complex = SubElement(schema_elem, "xsd:complexType", {"name": array_name})
        seq = SubElement(complex, "xsd:sequence")
        SubElement(seq, "xsd:element", {
            "name": "item",
            "type": item_xsd,
            "minOccurs": "0",
            "maxOccurs": "unbounded",
            "nillable": "true"
        })

        self._array_types.add(array_name)
        return f"tns:{array_name}"

    def _add_fields_to_sequence(self, sequence: Element, schema: dict, schema_elem: Element):
        """
        Populate an <xsd:sequence> with elements defined by a {name: type} schema dict.
        Handles List[T] and Optional[T] correctly.
        """
        for field_name, field_type in schema.items():
            origin = get_origin(field_type)
            args = get_args(field_type)

            min_occurs = "0" if origin is Optional else "1"
            actual_type = args[0] if origin is Optional and args else field_type

            if origin in (list, List):
                item_type = args[0] if args else str
                array_type = self._register_array_type(schema_elem, item_type)
                SubElement(sequence, "xsd:element", {
                    "name": field_name,
                    "type": array_type,
                    "minOccurs": min_occurs,
                    "nillable": "true"
                })
            else:
                SubElement(sequence, "xsd:element", {
                    "name": field_name,
                    "type": self._xsd_type(actual_type),
                    "minOccurs": min_occurs,
                    "nillable": "true"
                })

    # ------------------------------------------------------------------
    # WSDL Generation
    # ------------------------------------------------------------------
    def generate_wsdl(self) -> str:
        """
        Generate and return the complete WSDL document as a string.
        Called automatically when ?wsdl is present in the query string.
        """
        url = str(self.request.url)
        base_url = url.split('?')[0].rstrip('/')

        # Respect reverse-proxy headers – essential for nginx, Traefik, Cloudflare, etc.
        proto = self.request.headers.get("X-Forwarded-Proto",
                                         self.request.headers.get("X-Forwarded-Protocol", "http"))
        host = self.request.headers.get("X-Forwarded-Host",
                                        self.request.headers.get("Host"))

        if host:
            location = f"{proto}://{host}{base_url}"
        else:
            location = base_url

        # Highest priority: class-defined SERVICE_URL
        if hasattr(self.__class__, "SERVICE_URL") and self.__class__.SERVICE_URL:
            location = self.__class__.SERVICE_URL.rstrip("/")

        service_name = self.__class__.__name__
        tns = f"http://tempuri.org/{service_name.lower()}"

        root = Element("definitions", {
            "name": service_name,
            "targetNamespace": tns,
            "xmlns": "http://schemas.xmlsoap.org/wsdl/",
            "xmlns:tns": tns,
            "xmlns:soap": "http://schemas.xmlsoap.org/wsdl/soap/",
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
        })

        # <types>
        types = SubElement(root, "types")
        schema = SubElement(types, "xsd:schema", {
            "targetNamespace": tns,
            "elementFormDefault": "qualified"
        })

        # Build request & response types for every operation
        for op_name in self.get_operations():
            method = getattr(self, op_name)

            # Request message
            req_elem = SubElement(schema, "xsd:element", {"name": op_name})
            req_complex = SubElement(req_elem, "xsd:complexType")
            req_seq = SubElement(req_complex, "xsd:sequence")

            sig = inspect.signature(method)
            params = {
                name: param.annotation if param.annotation != param.empty else str
                for name, param in sig.parameters.items()
                if param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
            }

            if not params:
                SubElement(req_seq, "xsd:element", {"name": "dummy", "type": "xsd:string", "minOccurs": "0"})
            else:
                self._add_fields_to_sequence(req_seq, params, schema)

            # Response message
            resp_elem = SubElement(schema, "xsd:element", {"name": f"{op_name}Response"})
            resp_complex = SubElement(resp_elem, "xsd:complexType")
            resp_seq = SubElement(resp_complex, "xsd:sequence")

            result_wrapper = SubElement(resp_seq, "xsd:element", {"name": f"{op_name}Result"})
            return_schema = getattr(method, "_wsdl_return_schema", None)

            if return_schema:
                wrapper_complex = SubElement(result_wrapper, "xsd:complexType")
                wrapper_seq = SubElement(wrapper_complex, "xsd:sequence")
                self._add_fields_to_sequence(wrapper_seq, return_schema, schema)
            else:
                # Fallback for undecorated methods
                SubElement(result_wrapper, "xsd:complexType").append(
                    SubElement(SubElement(SubElement(result_wrapper, "xsd:complexType"), "xsd:sequence"),
                               "xsd:element",
                               {"name": "item", "type": "xsd:string", "minOccurs": "0", "maxOccurs": "unbounded"})
                )

        # <message>, <portType>, <binding>, <service>
        for op in self.get_operations():
            for suffix, elem_name in [("Request", op), ("Response", f"{op}Response")]:
                msg = SubElement(root, "message", {"name": f"{op}{suffix}"})
                SubElement(msg, "part", {"name": "parameters", "element": f"tns:{elem_name}"})

        port_type = SubElement(root, "portType", {"name": f"{service_name}PortType"})
        binding = SubElement(root, "binding", {"name": f"{service_name}Binding", "type": f"tns:{service_name}PortType"})
        SubElement(binding, "soap:binding", {"style": "document", "transport": "http://schemas.xmlsoap.org/soap/http"})

        for op in self.get_operations():
            # portType operation
            o = SubElement(port_type, "operation", {"name": op})
            SubElement(o, "input", {"message": f"tns:{op}Request"})
            SubElement(o, "output", {"message": f"tns:{op}Response"})

            # binding operation
            bo = SubElement(binding, "operation", {"name": op})
            SubElement(bo, "soap:operation", {"soapAction": f"{tns}#{op}"})
            for io in ("input", "output"):
                SubElement(SubElement(bo, io), "soap:body", {"use": "literal"})

        # <service>
        service = SubElement(root, "service", {"name": f"{service_name}Service"})
        port = SubElement(service, "port", {"name": f"{service_name}Port", "binding": f"tns:{service_name}Binding"})
        SubElement(port, "soap:address", {"location": location})

        return ET.tostring(root, encoding="unicode", method="xml")

    # ------------------------------------------------------------------
    # SOAP Request Handling
    # ------------------------------------------------------------------
    def handle(self) -> str:
        if "wsdl" in self.request.params:
            return self.generate_wsdl()

        try:
            root = ET.fromstring(self.request.raw_content)
            _SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
            body = root.find(f".//{{{_SOAP_NS}}}Body")
            if body is None or len(body) == 0:
                raise ValueError("No SOAP Body")

            operation_elem = body[0]
            operation_name = operation_elem.tag.split("}")[-1]


            args = {}
            for child in operation_elem:
                key = child.tag.split("}")[-1]  # e.g. "Numbers" or "item"

                # Case 1: Direct child (flat repeated style)
                if child.text is not None and child.text.strip() != "":
                    text_value = child.text.strip()
                    if key in args:
                        if not isinstance(args[key], list):
                            args[key] = [args[key]]
                        args[key].append(None if text_value == "" else text_value)
                    else:
                        args[key] = None if text_value == "" else text_value
                else:
                    # Case 2: Has children → likely an array with <item> elements
                    items = []
                    for item in child:
                        item_key = item.tag.split("}")[-1]
                        if item_key == "item":
                            val = (item.text or "").strip()
                            items.append(None if val == "" else val)
                    if items:
                        args[key] = items
                    elif len(child) == 0:
                        # Empty complex type (e.g. <Numbers></Numbers>)
                        args[key] = []

            method = getattr(self, operation_name)
            sig = inspect.signature(method)

            # ─── Build kwargs with automatic type conversion ───
            kwargs = {}
            for name, param in sig.parameters.items():
                if name == "self":
                    continue
                if name in args:
                    anno = param.annotation if param.annotation != param.empty else str
                    kwargs[name] = self._convert_param(args[name], anno)
                elif param.default is param.empty:
                    raise TypeError(f"Missing required parameter: {name}")

            if hasattr(self, "on_request"):
                self.on_request(self.request)

            result = method(**kwargs)

            if hasattr(self, "on_result"):
                result = self.on_result(result)

            # ─── Build correct SOAP response (repeating tags = field name) ───
            envelope = ET.Element("soapenv:Envelope", {
                "xmlns:soapenv": _SOAP_NS,
                "xmlns:tns": f"http://tempuri.org/{self.__class__.__name__.lower()}"
            })
            body_el = ET.SubElement(envelope, "soapenv:Body")
            resp = ET.SubElement(body_el, f"{operation_name}Response")
            result_el = ET.SubElement(resp, f"{operation_name}Result")

            for key, value in (result or {}).items():
                if isinstance(value, (list, tuple, set)):
                    for item in value:
                        el = ET.SubElement(result_el, key)
                        if item is None:
                            el.set("{http://www.w3.org/2001/XMLSchema-instance}nil", "true")
                        else:
                            el.text = str(item)
                else:
                    el = ET.SubElement(result_el, key)
                    if value is None:
                        el.set("{http://www.w3.org/2001/XMLSchema-instance}nil", "true")
                    else:
                        el.text = str(value)

            return ET.tostring(envelope, encoding="unicode", xml_declaration=True)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return self.soap_fault(str(e))

    # ------------------------------------------------------------------
    # SOAP Fault response
    # ------------------------------------------------------------------
    def soap_fault(self, message: str) -> str:
        """Return a minimal but valid SOAP Fault."""
        env = Element(str(QName("http://schemas.xmlsoap.org/soap/envelope/", "Envelope")))
        body = SubElement(env, str(QName("http://schemas.xmlsoap.org/soap/envelope/", "Body")))
        fault = SubElement(body, str(QName("http://schemas.xmlsoap.org/soap/envelope/", "Fault")))
        SubElement(fault, "faultcode").text = "Server"
        SubElement(fault, "faultstring").text = message
        return ET.tostring(env, encoding="unicode")


# ==============================================================
# Example usage with Tina4 routing
# ==============================================================
"""
from typing import List, Optional
from tina4_python import Tina4

class Calculator(WSDL):
    SERVICE_URL = "https://example.com/soap/calculator"

    @wsdl_operation({"Result": int})
    def Add(self, a: int, b: int):
        return {"Result": a + b}

    @wsdl_operation({
        "Numbers": List[int],
        "Total": int,
        "Error": Optional[str]
    })
    def SumList(self, Numbers: List[int]):
        return {
            "Numbers": Numbers,
            "Total": sum(Numbers),
            "Error": None
        }

# Tina4 route

@wsdl("/calculator") # implies /calculator?wsdl
async def wsdl_cis(request, response):

    return response.wsdl(Calculator(request))
"""