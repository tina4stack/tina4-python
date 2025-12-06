from tina4_python.WSDL import WSDL, wsdl_operation


class CIS(WSDL):
    SERVICE_URL = "http://localhost:7145/cis"

    def GetSession(self, ClientId: str, Password: str):
        client_id = ClientId
        password = Password

        return {"SessionId": "XXXX"}


    def get_new_session(self, client_id: str, password: str):


        return {"SessionId": "XXXX", "client_id": client_id, "password": password}

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
        return {
            "Numbers": Numbers,
            "Total": sum(Numbers),
            "Error": None
        }