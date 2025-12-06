from typing import get_origin, get_args, List, Optional, Dict, Any
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, QName
import inspect


# --------------------------------------------------------------
# Decorator: declare exact response structure
# --------------------------------------------------------------
def wsdl_operation(return_schema: dict):
    """
    Example:
        @wsdl_operation({
            "SessionId": str,
            "Expires": str,
            "Roles": List[str],
            "Error": Optional[str]
        })
        def Login(self, Username: str, Password: str): ...
    """

    def decorator(func):
        func._wsdl_return_schema = return_schema
        return func

    return decorator


# --------------------------------------------------------------
# Main WSDL Class – Fixed & Complete
# --------------------------------------------------------------
class WSDL:
    XSD_TYPES = {
        str: "xsd:string",
        int: "xsd:integer",
        float: "xsd:double",
        bool: "xsd:boolean",
    }

    def __init__(self, request):
        self.request = request
        self._array_types = set()  # Track registered ArrayOfX

    def get_operations(self):
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

    # ----------------------------------------------------------
    # Core helpers
    # ----------------------------------------------------------
    def _xsd_type(self, py_type):
        origin = get_origin(py_type)
        args = get_args(py_type)

        # Optional[T] → T
        if origin is Optional:
            py_type = args[0] if args else str

        if py_type in self.XSD_TYPES:
            return self.XSD_TYPES[py_type]
        return "xsd:string"

    def _register_array_type(self, schema_elem: Element, item_py_type) -> str:
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

    # ----------------------------------------------------------
    # WSDL Generation
    # ----------------------------------------------------------
    def generate_wsdl(self) -> str:
        url = str(self.request.url)
        base_url = url.split('?')[0].rstrip('/')  # remove ?wsdl and trailing slash

        # Respect X-Forwarded-* headers (critical for nginx, traefik, cloudflare, etc.)
        proto = self.request.headers.get("X-Forwarded-Proto",
                                         self.request.headers.get("X-Forwarded-Protocol", "http"))
        host = self.request.headers.get("X-Forwarded-Host",
                                        self.request.headers.get("Host"))

        if host:
            location = f"{proto}://{host}{base_url}"
        else:
            location = base_url

        # FALLBACK: if class defines SERVICE_URL, use that wins
        if hasattr(self.__class__, "SERVICE_URL"):
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

        for op_name in self.get_operations():
            method = getattr(self, op_name)

            # --- Request message ---
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

            # --- Response message ---
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
            # portType
            o = SubElement(port_type, "operation", {"name": op})
            SubElement(o, "input", {"message": f"tns:{op}Request"})
            SubElement(o, "output", {"message": f"tns:{op}Response"})

            # binding
            bo = SubElement(binding, "operation", {"name": op})
            SubElement(bo, "soap:operation", {"soapAction": f"{tns}#{op}"})
            for io in ("input", "output"):
                SubElement(SubElement(bo, io), "soap:body", {"use": "literal"})

        service = SubElement(root, "service", {"name": f"{service_name}Service"})
        port = SubElement(service, "port", {"name": f"{service_name}Port", "binding": f"tns:{service_name}Binding"})
        SubElement(port, "soap:address", {"location": location})

        return ET.tostring(root, encoding="unicode", method="xml")


    def handle(self) -> str:
        if "wsdl" in self.request.params:
            return self.generate_wsdl()

        try:
            root = ET.fromstring(self.request.raw_content)

            # Find SOAP Body (works with any prefix: ns0, soapenv, etc.)
            _SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
            body = root.find(f".//{{{_SOAP_NS}}}Body")
            if body is None or len(body) == 0:
                raise ValueError("No SOAP Body")

            operation_elem = body[0]
            operation_name = operation_elem.tag.split("}")[-1]

            # Extract all child elements → {local_name: text}
            args = {}
            for child in operation_elem:
                key = child.tag.split("}")[-1]           # strip namespace
                value = (child.text or "").strip()
                args[key] = None if value == "" else value

            # Call method with real named arguments
            method = getattr(self, operation_name)
            import inspect
            sig = inspect.signature(method)

            # Build kwargs only with parameters the method actually wants
            kwargs = {}
            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue
                if param_name in args:
                    kwargs[param_name] = args[param_name]
                elif param.default is param.empty:
                    raise TypeError(f"Missing required parameter: {param_name}")

            # Hooks
            if hasattr(self, "on_request"):
                self.on_request(self.request)

            result = method(**kwargs)

            if hasattr(self, "on_result"):
                result = self.on_result(result)

            # Build response
            envelope = ET.Element("soapenv:Envelope", {
                "xmlns:soapenv": _SOAP_NS,
                "xmlns:tns": f"http://tempuri.org/{self.__class__.__name__.lower()}"
            })
            body_el = ET.SubElement(envelope, "soapenv:Body")
            resp = ET.SubElement(body_el, f"{operation_name}Response")
            result_el = ET.SubElement(resp, f"{operation_name}Result")

            for key, value in (result or {}).items():
                if value is None:
                    el = ET.SubElement(result_el, key)
                    el.set("{http://www.w3.org/2001/XMLSchema-instance}nil", "true")
                elif isinstance(value, (list, tuple)):
                    item_tag = key.rstrip("[]") + "Item" if key.endswith("[]") else "item"
                    for v in value:
                        el = ET.SubElement(result_el, item_tag)
                        el.text = str(v)
                else:
                    el = ET.SubElement(result_el, key)
                    el.text = str(value)

            return ET.tostring(envelope, encoding="unicode", xml_declaration=True)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return self.soap_fault(str(e))

    def soap_fault(self, message: str) -> str:
        env = Element(QName("http://schemas.xmlsoap.org/soap/envelope/", "Envelope"))
        body = SubElement(env, QName("http://schemas.xmlsoap.org/soap/envelope/", "Body"))
        fault = SubElement(body, QName("http://schemas.xmlsoap.org/soap/envelope/", "Fault"))
        SubElement(fault, "faultcode").text = "Server"
        SubElement(fault, "faultstring").text = message
        return ET.tostring(env, encoding="unicode")
