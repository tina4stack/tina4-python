from typing import Dict, Any, Callable
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import QName

class WSDL:
    """
    Base class for implementing WSDL-compliant web services in Tina4Python.

    This class handles SOAP request parsing, method dispatching, response generation,
    and WSDL XML output when '?wsdl' is queried. It provides a foundation for defining
    SOAP services comparable to frameworks like FastAPI or Flask with SOAP extensions.

    Key Features:
    - Parses incoming SOAP envelopes to extract operation and parameters.
    - Dispatches to subclass methods based on operation name.
    - Converts method return dict to SOAP response XML.
    - Generates basic WSDL XML describing the service, operations, and simple types.
    - Supports pre/post hooks: on_request and on_result for request/response manipulation.

    Limitations and Suggestions:
    - Assumes all parameters and return values are strings for simplicity. For complex types,
      extend generate_wsdl() using type hints or pydantic models.
    - WSDL types are basic; consider integrating with libraries like spyne for advanced schemas if needed.
    - Error handling is minimal; extend soap_fault() for custom faults.
    - XML namespaces are hardcoded; customize as required.

    Usage Example:
    Define a subclass with operation methods:

    class CIS(WSDL):
        def on_request(self, request):
            # Optional: Validate or modify the request (e.g., check headers)
            pass

        def on_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
            # Optional: Modify the result dict before XML conversion
            return result

        def GetSession(self, params: Callable[[str], Any]) -> Dict[str, Any]:
            client_id = params("ClientId")
            password = params("Password")
            # Implement business logic here
            if not client_id or not password:
                return {"Error": "Invalid credentials"}
            return {"SessionId": "XXXX"}

    In your route (using @wsdl decorator):
    @wsdl("/cis")
    async def wsdl_cis(request, response):
        return await response.wsdl(CIS(request))

    This setup allows handling SOAP POST requests and GET ?wsdl for the spec.
    Test with tools like SoapUI or curl for SOAP envelopes.
    """

    def __init__(self, request):
        """
        Initialize with the incoming request object.

        Args:
            request: The request object from Tina4Python.
        """
        self.request = request

    def get_operations(self) -> list[str]:
        """
        Retrieve list of operation names (public callable methods excluding hooks).

        Returns:
            List of operation names.
        """
        excluded = {'on_request', 'on_result', 'handle', 'get_operations', 'generate_wsdl', 'soap_fault'}
        return [
            name for name in dir(self)
            if callable(getattr(self, name)) and not name.startswith('_') and name not in excluded
        ]

    def generate_wsdl(self) -> str:
        """
        Generate WSDL XML describing the service.

        This produces a basic document/literal wrapped style WSDL.
        Assumes operations take/return simple string-based messages.
        Extend for complex types based on method signatures.

        Returns:
            WSDL XML as string.
        """
        location = str(self.request.url).split('?')[0]  # Service endpoint URL without query
        service_name = self.__class__.__name__
        tns = f"http://example.com/{service_name}"  # Target namespace; customize as needed

        # Root definitions
        wsdl = ET.Element("definitions", {
            "name": service_name,
            "targetNamespace": tns,
            "xmlns": "http://schemas.xmlsoap.org/wsdl/",
            "xmlns:soap": "http://schemas.xmlsoap.org/wsdl/soap/",
            "xmlns:tns": tns,
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema"
        })

        # Types section (basic; assumes string params/returns)
        types = ET.SubElement(wsdl, "types")
        schema = ET.SubElement(types, "xsd:schema", {"targetNamespace": tns})
        for op in self.get_operations():
            # Input type (wrapper for parameters)
            input_type = ET.SubElement(schema, "xsd:element", {"name": op})
            ET.SubElement(input_type, "xsd:complexType")  # Add sequence/elements if params known

            # Response type (wrapper for result)
            output_type = ET.SubElement(schema, "xsd:element", {"name": f"{op}Response"})
            ET.SubElement(output_type, "xsd:complexType")  # Extend with actual fields

        # Messages
        for op in self.get_operations():
            # Request message
            msg_req = ET.SubElement(wsdl, "message", {"name": f"{op}Request"})
            ET.SubElement(msg_req, "part", {"name": "parameters", "element": f"tns:{op}"})

            # Response message
            msg_res = ET.SubElement(wsdl, "message", {"name": f"{op}Response"})
            ET.SubElement(msg_res, "part", {"name": "parameters", "element": f"tns:{op}Response"})

        # PortType
        port_type = ET.SubElement(wsdl, "portType", {"name": f"{service_name}PortType"})
        for op in self.get_operations():
            operation = ET.SubElement(port_type, "operation", {"name": op})
            ET.SubElement(operation, "input", {"message": f"tns:{op}Request"})
            ET.SubElement(operation, "output", {"message": f"tns:{op}Response"})

        # Binding
        binding = ET.SubElement(wsdl, "binding", {"name": f"{service_name}Binding", "type": f"tns:{service_name}PortType"})
        ET.SubElement(binding, "soap:binding", {"style": "document", "transport": "http://schemas.xmlsoap.org/soap/http"})
        for op in self.get_operations():
            operation = ET.SubElement(binding, "operation", {"name": op})
            ET.SubElement(operation, "soap:operation", {"soapAction": f"{tns}/{op}"})
            input = ET.SubElement(operation, "input")
            ET.SubElement(input, "soap:body", {"use": "literal"})
            output = ET.SubElement(operation, "output")
            ET.SubElement(output, "soap:body", {"use": "literal"})

        # Service
        service = ET.SubElement(wsdl, "service", {"name": f"{service_name}Service"})
        port = ET.SubElement(service, "port", {"name": f"{service_name}Port", "binding": f"tns:{service_name}Binding"})
        ET.SubElement(port, "soap:address", {"location": location})

        # Convert to string
        ET.register_namespace('', "http://schemas.xmlsoap.org/wsdl/")
        ET.register_namespace('soap', "http://schemas.xmlsoap.org/wsdl/soap/")
        return ET.tostring(wsdl, encoding='unicode', method='xml')

    def handle(self) -> str:
        """
        Main handler: Check for ?wsdl or process SOAP request.

        Returns:
            XML content as string (WSDL or SOAP response/fault).
        """
        if 'wsdl' in self.request.params:
            return self.generate_wsdl()

        # Process SOAP request (assume POST with XML body)
        try:
            body = self.request.body
            root = ET.fromstring(body)
            soap_ns = {'soap': 'http://schemas.xmlsoap.org/soap/envelope/'}
            body_elem = root.find('soap:Body', soap_ns)
            if body_elem is None:
                raise ValueError("Invalid SOAP envelope")

            operation_elem = list(body_elem)[0]
            operation = QName(operation_elem.tag).localname

            # Params as callable: params(key) -> value or None
            def params(key: str) -> Any:
                elem = operation_elem.find(key)
                return elem.text if elem is not None else None

            # Pre-hook
            if hasattr(self, 'on_request'):
                self.on_request(self.request)

            # Dispatch to operation
            if operation in self.get_operations():
                method = getattr(self, operation)
                result = method(params)
            else:
                raise ValueError(f"Operation '{operation}' not found")

            # Post-hook
            if hasattr(self, 'on_result'):
                result = self.on_result(result)

            # Build SOAP response
            envelope = ET.Element(str(QName('http://schemas.xmlsoap.org/soap/envelope/', 'Envelope')))
            body = ET.SubElement(envelope, str(QName('http://schemas.xmlsoap.org/soap/envelope/', 'Body')))
            res_elem = ET.SubElement(body, f"{operation}Response")
            for key, value in result.items():
                elem = ET.SubElement(res_elem, key)
                elem.text = str(value)

            return ET.tostring(envelope, encoding='unicode', method='xml')

        except Exception as e:
            return self.soap_fault(str(e))

    def soap_fault(self, message: str) -> str:
        """
        Generate SOAP fault response.

        Args:
            message: Fault message.

        Returns:
            Fault XML as string.
        """
        envelope = ET.Element(str(QName('http://schemas.xmlsoap.org/soap/envelope/', 'Envelope')))
        body = ET.SubElement(envelope, str(QName('http://schemas.xmlsoap.org/soap/envelope/', 'Body')))
        fault = ET.SubElement(body, str(QName('http://schemas.xmlsoap.org/soap/envelope/', 'Fault')))
        ET.SubElement(fault, 'faultcode').text = 'Server'
        ET.SubElement(fault, 'faultstring').text = message

        return ET.tostring(envelope, encoding='unicode', method='xml')