from tina4_python.WSDL import WSDL, wsdl_operation
from typing import List

class Calculator(WSDL):
    SERVICE_URL = "http://localhost:7145/calculator"

    def Add(self, a: int, b: int):
        return {"Result": a + b}

    def SumList(self, Numbers: List[int]):

        return {
            "Numbers": Numbers,
            "Total": sum(Numbers),
            "Error": None
        }