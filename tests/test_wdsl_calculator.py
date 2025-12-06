# tests/test_soap_calculator.py
import pytest
import requests
import xml.etree.ElementTree as ET

# ------------------------------------------------------------------
# Configuration – change only if your port/path changes
# ------------------------------------------------------------------
BASE_URL = "http://localhost:7145"
WSDL_URL = f"{BASE_URL}/calculator?wsdl"
SOAP_URL = f"{BASE_URL}/calculator"

# SOAP headers
HEADERS = {
    "Content-Type": "text/xml; charset=utf-8",
    "SOAPAction": '""'
}

# ------------------------------------------------------------------
# Helper to send SOAP request
# ------------------------------------------------------------------
def send_soap(payload: str) -> ET.Element:
    response = requests.post(SOAP_URL, data=payload.strip(), headers=HEADERS)
    response.raise_for_status()  # Will raise if not 200
    return ET.fromstring(response.content)


# ------------------------------------------------------------------
# 1. WSDL is served and valid
# ------------------------------------------------------------------
def test_wsdl_is_served_and_valid():
    resp = requests.get(WSDL_URL)
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["Content-Type"]
    xml = resp.text

    assert '<definitions' in xml
    assert "Calculator" in xml
    assert "Add" in xml
    assert "SumList" in xml
    assert "ArrayOfInt" in xml or "ArrayOfInteger" in xml
    assert "http://localhost:7145/calculator" in xml


# ------------------------------------------------------------------
# 2. Add operation works
# ------------------------------------------------------------------
def test_add_operation():
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

    root = send_soap(payload)
    result = root.find(".//AddResult/Result")
    assert result is not None
    assert result.text == "42"


# ------------------------------------------------------------------
# 3. SumList – repeated elements → correct response with <Numbers> tags
# ------------------------------------------------------------------
def test_sumlist_repeated_elements():
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

    root = send_soap(payload)

    numbers = root.findall(".//SumListResult/Numbers")
    assert len(numbers) == 3
    assert [el.text for el in numbers] == ["100", "200", "300"]

    total = root.find(".//SumListResult/Total")
    assert total is not None
    assert total.text == "600"

    error = root.find(".//SumListResult/Error")
    assert error.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true"


# ------------------------------------------------------------------
# 4. Empty list returns 0 and no <Numbers> tags
# ------------------------------------------------------------------
def test_sumlist_empty_list():
    payload = """
    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                      xmlns:cal="http://tempuri.org/calculator">
       <soapenv:Header/>
       <soapenv:Body>
          <cal:SumList/>
       </soapenv:Body>
    </soapenv:Envelope>
    """

    root = send_soap(payload)

    assert len(root.findall(".//SumListResult/Total")) == 0
    assert len(root.findall(".//SumListResult/Numbers")) == 0


# ------------------------------------------------------------------
# 5. Missing parameter → SOAP Fault
# ------------------------------------------------------------------
def test_missing_parameter_raises_fault():
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

    resp = requests.post(SOAP_URL, data=payload.strip(), headers=HEADERS)
    root = ET.fromstring(resp.content)
    fault = root.find(".//faultstring")
    assert fault is not None
    assert "Missing required parameter" in fault.text


# ------------------------------------------------------------------
# 6. Invalid number → ValueError → SOAP Fault
# ------------------------------------------------------------------
def test_invalid_number_causes_fault():
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

    resp = requests.post(SOAP_URL, data=payload.strip(), headers=HEADERS)
    root = ET.fromstring(resp.content)
    fault = root.find(".//faultstring")
    assert "invalid literal for int()" in fault.text