# WSDL / SOAP

Tina4 includes zero-dependency SOAP 1.1 support with automatic WSDL generation from Python type annotations. Define service methods with `@wsdl_operation`, and the framework generates both the WSDL definition and handles SOAP XML request/response.

## Basic Service

```python
from tina4_python.wsdl import WSDL, wsdl_operation
from tina4_python.core.router import get, post

class Calculator(WSDL):
    @wsdl_operation({"Result": int})
    def Add(self, a: int, b: int):
        return {"Result": a + b}

    @wsdl_operation({"Result": int})
    def Subtract(self, a: int, b: int):
        return {"Result": a - b}

    @wsdl_operation({"Result": float})
    def Divide(self, a: float, b: float):
        if b == 0:
            return {"Result": 0.0}
        return {"Result": a / b}

@get("/calculator")
@post("/calculator")
async def calculator_endpoint(request, response):
    service = Calculator(request)
    return response(service.handle())
```

- `GET /calculator?wsdl` returns the WSDL definition XML
- `POST /calculator` with SOAP XML invokes operations

## Complex Types

Use Python type hints including `List` and `Optional` for complex operations.

```python
from typing import List, Optional
from tina4_python.wsdl import WSDL, wsdl_operation

class OrderService(WSDL):
    @wsdl_operation({"Total": int, "Average": float, "Error": Optional[str]})
    def SumList(self, Numbers: List[int]):
        if not Numbers:
            return {"Total": 0, "Average": 0.0, "Error": "Empty list"}
        return {
            "Total": sum(Numbers),
            "Average": sum(Numbers) / len(Numbers),
            "Error": None,
        }

    @wsdl_operation({"OrderId": str, "Status": str})
    def PlaceOrder(self, CustomerId: str, ProductId: str, Quantity: int):
        order_id = create_order(CustomerId, ProductId, Quantity)
        return {"OrderId": order_id, "Status": "confirmed"}
```

## Type Mapping

Python types are automatically mapped to XSD types in the WSDL:

| Python Type | XSD Type |
|-------------|----------|
| `str` | `xsd:string` |
| `int` | `xsd:int` |
| `float` | `xsd:double` |
| `bool` | `xsd:boolean` |
| `bytes` | `xsd:base64Binary` |
| `List[T]` | Array of T |
| `Optional[T]` | Nullable T |

## Lifecycle Hooks

Override `on_request` and `on_result` for pre/post processing.

```python
class SecureService(WSDL):
    def on_request(self, request):
        """Validate or log before method invocation."""
        api_key = request.headers.get("x-api-key")
        if not api_key:
            raise PermissionError("API key required")

    def on_result(self, result):
        """Transform or audit after method returns."""
        # Log the result, add metadata, etc.
        return result

    @wsdl_operation({"Balance": float})
    def GetBalance(self, AccountId: str):
        return {"Balance": lookup_balance(AccountId)}
```

## SOAP Request Format

Clients send SOAP XML to invoke operations:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:tns="http://localhost/calculator">
    <soapenv:Body>
        <tns:Add>
            <a>5</a>
            <b>3</b>
        </tns:Add>
    </soapenv:Body>
</soapenv:Envelope>
```

## SOAP Response Format

```xml
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:tns="http://localhost/calculator">
    <soapenv:Body>
        <tns:AddResponse>
            <Result>8</Result>
        </tns:AddResponse>
    </soapenv:Body>
</soapenv:Envelope>
```

## Multiple Services

Define separate WSDL classes for different service domains.

```python
class UserService(WSDL):
    @wsdl_operation({"UserId": str, "Name": str})
    def CreateUser(self, Name: str, Email: str):
        user = User({"name": Name, "email": Email})
        user.save()
        return {"UserId": str(user.id), "Name": Name}

class ReportService(WSDL):
    @wsdl_operation({"ReportUrl": str})
    def GenerateReport(self, ReportType: str, DateFrom: str, DateTo: str):
        url = generate_report(ReportType, DateFrom, DateTo)
        return {"ReportUrl": url}

@get("/services/users")
@post("/services/users")
async def user_service(request, response):
    return response(UserService(request).handle())

@get("/services/reports")
@post("/services/reports")
async def report_service(request, response):
    return response(ReportService(request).handle())
```

## Tips

- The `@wsdl_operation` decorator is required on every public service method.
- Type annotations on method parameters control automatic value conversion from XML.
- The response schema dict in `@wsdl_operation({...})` defines the WSDL output types.
- Use `GET /endpoint?wsdl` to retrieve the WSDL definition for client generation.
- Method names in the WSDL class become SOAP operation names -- use PascalCase by convention.
