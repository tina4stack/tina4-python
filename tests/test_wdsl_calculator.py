# tests/test_wdsl_calculator.py
"""
Self-contained WSDL/SOAP Calculator test suite.

Defines the Calculator WSDL service and route inline, then tests via
Router.resolve() — no running server required.
"""

import pytest
import xml.etree.ElementTree as ET
import tina4_python
from tina4_python import Constant
from tina4_python.Router import Router, get, post
from tina4_python.WSDL import WSDL
from typing import List


# ------------------------------------------------------------------
# Inline Calculator WSDL service
# ------------------------------------------------------------------
class Calculator(WSDL):
    SERVICE_URL = "http://localhost:7145/calculator"

    def Add(self, a: int, b: int):
        return {"Result": a + b}

    def SumList(self, Numbers: List[int]):
        return {
            "Numbers": Numbers,
            "Total": sum(Numbers),
            "Error": None,
        }


# ------------------------------------------------------------------
# Fixture: register the WSDL route before each test
# ------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_routes():
    saved = dict(tina4_python.tina4_routes)
    tina4_python.tina4_routes = {}

    # Register /calculator for GET (wsdl) and POST (soap)
    @get("/calculator")
    @post("/calculator")
    async def wsdl_calculator(request, response):
        from tina4_python.Response import Response as Resp
        return Resp.wsdl(Calculator(request))

    yield
    tina4_python.tina4_routes = saved


def _make_request(params=None, body=None, raw_content=None):
    """Build a minimal request dict for Router.resolve()."""
    return {
        "params": params or {},
        "body": body or {},
        "files": {},
        "raw_data": None,
        "raw_request": None,
        "raw_content": raw_content,
        "asgi_scope": None,
        "asgi_reader": None,
        "asgi_writer": None,
        "asgi_response": None,
    }


async def resolve_soap(payload: str):
    """Send a SOAP POST to /calculator and return parsed XML root."""
    token = tina4_python.tina4_auth.get_token({"url": "/calculator"})
    req = _make_request(
        body={},
        raw_content=payload.strip(),
    )
    headers = {
        "content-type": "text/xml; charset=utf-8",
        "soapaction": '""',
        "authorization": f"Bearer {token}",
    }
    r = await Router.resolve(Constant.TINA4_POST, "/calculator", req, headers, {})
    content = r.content if isinstance(r.content, str) else r.content.decode()
    return ET.fromstring(content)


async def resolve_wsdl():
    """GET /calculator?wsdl and return the raw XML string."""
    req = _make_request(params={"wsdl": ""})
    token = tina4_python.tina4_auth.get_token({"url": "/calculator"})
    headers = {
        "content-type": "text/xml; charset=utf-8",
        "authorization": f"Bearer {token}",
    }
    r = await Router.resolve(Constant.TINA4_GET, "/calculator?wsdl", req, headers, {})
    return r.content if isinstance(r.content, str) else r.content.decode()


# ------------------------------------------------------------------
# 1. WSDL is served and valid
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wsdl_is_served_and_valid():
    xml = await resolve_wsdl()
    assert "<definitions" in xml
    assert "Calculator" in xml
    assert "Add" in xml
    assert "SumList" in xml
    assert "http://localhost:7145/calculator" in xml


# ------------------------------------------------------------------
# 2. Add operation works
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_add_operation():
    payload = """
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                      xmlns:cal="http://tempuri.org/calculator">
       <soapenv:Header/>
       <soapenv:Body>
          <cal:Add>
             <cal:a>33</cal:a>
             <cal:b>9</cal:b>
          </cal:Add>
       </soapenv:Body>
    </soapenv:Envelope>
    """
    root = await resolve_soap(payload)
    result = root.find(".//AddResult/Result")
    assert result is not None
    assert result.text == "42"


# ------------------------------------------------------------------
# 3. SumList – repeated elements
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sumlist_repeated_elements():
    payload = """
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                      xmlns:cal="http://tempuri.org/calculator">
       <soapenv:Header/>
       <soapenv:Body>
          <cal:SumList>
             <cal:Numbers>100</cal:Numbers>
             <cal:Numbers>200</cal:Numbers>
             <cal:Numbers>300</cal:Numbers>
          </cal:SumList>
       </soapenv:Body>
    </soapenv:Envelope>
    """
    root = await resolve_soap(payload)

    numbers = root.findall(".//SumListResult/Numbers")
    assert len(numbers) == 3
    assert [el.text for el in numbers] == ["100", "200", "300"]

    total = root.find(".//SumListResult/Total")
    assert total is not None
    assert total.text == "600"

    error = root.find(".//SumListResult/Error")
    assert error.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true"


# ------------------------------------------------------------------
# 4. Empty list returns no result elements
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sumlist_empty_list():
    payload = """
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                      xmlns:cal="http://tempuri.org/calculator">
       <soapenv:Header/>
       <soapenv:Body>
          <cal:SumList/>
       </soapenv:Body>
    </soapenv:Envelope>
    """
    root = await resolve_soap(payload)
    assert len(root.findall(".//SumListResult/Total")) == 0
    assert len(root.findall(".//SumListResult/Numbers")) == 0


# ------------------------------------------------------------------
# 5. Missing parameter → SOAP Fault
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_parameter_raises_fault():
    payload = """
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                      xmlns:cal="http://tempuri.org/calculator">
       <soapenv:Body>
          <cal:Add>
             <cal:a>10</cal:a>
          </cal:Add>
       </soapenv:Body>
    </soapenv:Envelope>
    """
    root = await resolve_soap(payload)
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault/faultstring")
    if fault is None:
        fault = root.find(".//faultstring")
    assert fault is not None
    assert "Missing required parameter" in fault.text


# ------------------------------------------------------------------
# 6. Invalid number → SOAP Fault
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_number_causes_fault():
    payload = """
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                      xmlns:cal="http://tempuri.org/calculator">
       <soapenv:Body>
          <cal:SumList>
             <cal:Numbers>123</cal:Numbers>
             <cal:Numbers>not_a_number</cal:Numbers>
          </cal:SumList>
       </soapenv:Body>
    </soapenv:Envelope>
    """
    root = await resolve_soap(payload)
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault/faultstring")
    if fault is None:
        fault = root.find(".//faultstring")
    assert fault is not None
    assert "invalid literal for int()" in fault.text
