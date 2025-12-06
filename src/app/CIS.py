from tina4_python.WSDL import WSDL


class CIS(WSDL):

    def GetSession(self, ClientId: str, Password: str):
        client_id = ClientId
        password = Password

        return {"SessionId": "XXXX"}
