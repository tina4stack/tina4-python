from tina4_python.WSDL import WSDL, wsdl_operation
from typing import List, Optional

class Calculator(WSDL):
    SERVICE_URL = "http://localhost:7145/calculator"

    @wsdl_operation({"Result": int})
    def Add(self, a: int, b: int):
        return {"Result": a + b}

    @wsdl_operation({
        "Numbers": List[int],
        "Total": int,
        "Error": Optional[str]
    })
    def SumList(self, Numbers: List[int]):

        Debug.info(f"SumList: {Numbers}")
        return {
            "Numbers": Numbers,
            "Total": sum(Numbers),
            "Error": None
        }