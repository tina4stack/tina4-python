"""A SOAP body that is not plain UTF-8 is refused before any parse.

THE BUG, MEASURED on v3 (958377c) through the REAL request path
(Request.from_scope -> WSDL.handle, bytes exactly as the ASGI server hands them):
a SOAP envelope with an internal DTD entity, encoded as UTF-16LE WITHOUT a byte
order mark, came back with the entity EXPANDED in the Echo result. Those bytes
(ASCII interleaved with NULs) are valid UTF-8, so the body decoded, the
``<!DOCTYPE`` guard - a regex over the decoded text - never matched ``<\\0!\\0D...``,
and the XML parser then honoured the declared ``encoding="UTF-16"`` and read
the DTD. SOAP 1.1 section 3 forbids a DTD; the guard exists precisely so no DTD
is ever read.

THE RULE (parity with tina4-php): refuse, with the Client fault "Malformed XML",
any body that starts with a byte order mark, is not valid UTF-8, contains a NUL,
or has an XML declaration naming an encoding other than UTF-8. The guard then
sees exactly the text the parser sees.
"""
import pytest

from tina4_python.core.request import Request
from tina4_python.wsdl import WSDL, wsdl_operation


class ParityService(WSDL):
    @wsdl_operation({"Result": str})
    def Echo(self, text: str):
        return {"Result": text}


ENVELOPE_WITH_DTD = (
    '<?xml version="1.0" encoding="{encoding}"?>'
    '<!DOCTYPE soap:Envelope [<!ENTITY e "EXPANDED">]>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:t="urn:tina4:parity">'
    '<soap:Body><t:Echo><t:text>&e;</t:text></t:Echo></soap:Body></soap:Envelope>'
)
PLAIN_ECHO = (
    '<?xml version="1.0" encoding="{encoding}"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:t="urn:tina4:parity">'
    '<soap:Body><t:Echo><t:text>hello</t:text></t:Echo></soap:Body></soap:Envelope>'
)
MALFORMED = "<faultcode>Client</faultcode><faultstring>Malformed XML</faultstring>"


def _handle(body: bytes) -> str:
    scope = {"type": "http", "method": "POST", "path": "/soap", "query_string": b"",
             "headers": [(b"content-type", b"text/xml; charset=utf-8")], "client": ("127.0.0.1", 5555)}
    return ParityService(Request.from_scope(scope, body)).handle()


@pytest.mark.parametrize("body", [
    pytest.param(ENVELOPE_WITH_DTD.format(encoding="UTF-16").encode("utf-16-le"), id="utf16le-no-bom"),
    pytest.param(ENVELOPE_WITH_DTD.format(encoding="UTF-16").encode("utf-16-be"), id="utf16be-no-bom"),
    pytest.param(b"\xff\xfe" + ENVELOPE_WITH_DTD.format(encoding="UTF-16").encode("utf-16-le"), id="utf16le-bom"),
    pytest.param(b"\xef\xbb\xbf" + PLAIN_ECHO.format(encoding="UTF-8").encode(), id="utf8-bom"),
    pytest.param(PLAIN_ECHO.format(encoding="UTF-8").encode().replace(b"hello", b"hel\x00lo"), id="nul-byte"),
    pytest.param(PLAIN_ECHO.format(encoding="ISO-8859-1").encode(), id="declared-latin1"),
    pytest.param(PLAIN_ECHO.format(encoding="UTF-7").encode(), id="declared-utf7"),
    pytest.param(PLAIN_ECHO.format(encoding="UTF-8").encode().replace(b"hello", b"hel\xfflo"), id="invalid-utf8"),
])
def test_a_body_that_is_not_plain_utf8_is_refused(body):
    response = _handle(body)
    assert MALFORMED in response, response
    assert "EXPANDED" not in response


@pytest.mark.parametrize("declared", ["UTF-8", "utf-8", "utf8"])
def test_plain_utf8_still_works(declared):
    """Positive control: the rule refuses what it must and nothing else."""
    response = _handle(PLAIN_ECHO.format(encoding=declared).encode())
    assert "<Result>hello</Result>" in response, response


def test_a_body_with_no_xml_declaration_still_works():
    body = PLAIN_ECHO.format(encoding="UTF-8").split("?>", 1)[1].encode()
    assert "<Result>hello</Result>" in _handle(body)


def test_a_utf8_doctype_keeps_its_own_fault():
    response = _handle(ENVELOPE_WITH_DTD.format(encoding="UTF-8").encode())
    assert "DOCTYPE declarations are not allowed in SOAP messages" in response
    assert "EXPANDED" not in response
