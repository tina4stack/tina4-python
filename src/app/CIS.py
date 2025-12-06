from tina4_python.WSDL import WSDL


class CIS(WSDL):
    SERVICE_URL = "http://localhost:7145/cis"

    def GetSession(self, ClientId: str, Password: str):
        client_id = ClientId
        password = Password

        return {"SessionId": "XXXX"}


    def get_new_session(self, client_id: str, password: str):


        return {"SessionId": "XXXX", "client_id": client_id, "password": password}