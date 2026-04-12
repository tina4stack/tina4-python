"""Test WSDL/SOAP engine — demonstrates: service creation, WSDL generation,
SOAP XML parsing, and operation execution.
"""
import pytest
from tina4_python.wsdl import WSDL, wsdl_operation


class FakeRequest:
    """Minimal request mock for WSDL tests."""

    def __init__(self, body="", method="POST", url="/api/soap/orders", params=None):
        self.body = body
        self.method = method
        self.url = url
        self.params = params or {}


class OrderService(WSDL):
    """Test SOAP service mirroring the store's order service."""

    @wsdl_operation({"order_id": "int", "status": "string"})
    def place_order(self, customer_id: int, product_ids: str, quantities: str):
        pids = [int(x) for x in product_ids.split(",")]
        qtys = [int(x) for x in quantities.split(",")]
        return {"order_id": 1, "status": "pending"}

    @wsdl_operation({"order_id": "int", "status": "string", "total": "float"})
    def get_order_status(self, order_id: int):
        if order_id == 1:
            return {"order_id": 1, "status": "pending", "total": 29.99}
        return {"order_id": order_id, "status": "not_found", "total": 0}


class TestWSDLServiceCreation:
    def test_discovers_operations(self):
        service = OrderService(service_url="/api/soap/orders")
        ops = service._operations
        assert "place_order" in ops
        assert "get_order_status" in ops

    def test_operation_count(self):
        service = OrderService(service_url="/api/soap/orders")
        assert len(service._operations) == 2


class TestWSDLGeneration:
    def test_generate_wsdl_contains_service(self):
        service = OrderService(service_url="/api/soap/orders")
        wsdl_doc = service.generate_wsdl()
        assert "OrderService" in wsdl_doc
        assert "definitions" in wsdl_doc

    def test_generate_wsdl_contains_operations(self):
        service = OrderService(service_url="/api/soap/orders")
        wsdl_doc = service.generate_wsdl()
        assert "place_order" in wsdl_doc
        assert "get_order_status" in wsdl_doc

    def test_generate_wsdl_contains_types(self):
        service = OrderService(service_url="/api/soap/orders")
        wsdl_doc = service.generate_wsdl()
        assert "xsd:schema" in wsdl_doc
        assert "xsd:element" in wsdl_doc

    def test_generate_wsdl_contains_binding(self):
        service = OrderService(service_url="/api/soap/orders")
        wsdl_doc = service.generate_wsdl()
        assert "OrderServiceBinding" in wsdl_doc
        assert "soap:binding" in wsdl_doc

    def test_generate_wsdl_contains_port(self):
        service = OrderService(service_url="/api/soap/orders")
        wsdl_doc = service.generate_wsdl()
        assert "OrderServicePort" in wsdl_doc
        assert "soap:address" in wsdl_doc
        assert "/api/soap/orders" in wsdl_doc


class TestSOAPRequestParsing:
    def _soap_envelope(self, operation_xml: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            "<soap:Body>"
            f"{operation_xml}"
            "</soap:Body>"
            "</soap:Envelope>"
        )

    def test_place_order_via_soap(self):
        xml = self._soap_envelope(
            "<place_order>"
            "<customer_id>1</customer_id>"
            "<product_ids>10,20</product_ids>"
            "<quantities>2,3</quantities>"
            "</place_order>"
        )
        request = FakeRequest(body=xml, method="POST")
        service = OrderService(request, service_url="/api/soap/orders")
        result = service.handle()

        assert "place_orderResponse" in result
        assert "<order_id>1</order_id>" in result
        assert "<status>pending</status>" in result

    def test_get_order_status_via_soap(self):
        xml = self._soap_envelope(
            "<get_order_status>"
            "<order_id>1</order_id>"
            "</get_order_status>"
        )
        request = FakeRequest(body=xml, method="POST")
        service = OrderService(request, service_url="/api/soap/orders")
        result = service.handle()

        assert "get_order_statusResponse" in result
        assert "<status>pending</status>" in result
        assert "<total>29.99</total>" in result

    def test_unknown_operation_returns_fault(self):
        xml = self._soap_envelope(
            "<unknown_op><foo>bar</foo></unknown_op>"
        )
        request = FakeRequest(body=xml, method="POST")
        service = OrderService(request, service_url="/api/soap/orders")
        result = service.handle()

        assert "Fault" in result
        assert "Unknown operation" in result

    def test_malformed_xml_returns_fault(self):
        request = FakeRequest(body="not xml at all", method="POST")
        service = OrderService(request, service_url="/api/soap/orders")
        result = service.handle()

        assert "Fault" in result
        assert "Malformed XML" in result

    def test_get_request_returns_wsdl(self):
        request = FakeRequest(body="", method="GET")
        service = OrderService(request, service_url="/api/soap/orders")
        result = service.handle()

        assert "definitions" in result
        assert "OrderService" in result
