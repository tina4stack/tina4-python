from tina4_python.WSDL import WSDL


class CIS(WSDL):

    def GetSession(self, params):
        client_id = params("ClientId")
        password = params("Password")

        return {"SessionId": "XXXX"}
