#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import os
from http import cookies
import hashlib
import tina4_python


class Session():

    def __init__(self, _default_name="PY_SESS", _default_path="./sessions"):
        self.session_name = _default_name
        self.cookie = cookies.SimpleCookie()
        self.session_path = _default_path
        self.session_values = None

    def start(self, _hash=None):
        # create a file for the session?
        # set the cookie for the session
        token = tina4_python.tina4_auth.get_token(payload_data={"session": True})
        if _hash is None:
            file_hash = hashlib.md5(token.encode()).hexdigest()
        else:
            file_hash = _hash
        if not os.path.exists(self.session_path):
            os.makedirs(self.session_path)
        with open(self.session_path + os.sep + file_hash, "w") as file:
            file.write(token)
        return hashlib.md5(token.encode()).hexdigest()

    def load(self, _hash):
        if os.path.isfile(self.session_path + os.sep):
            with open(self.session_path + os.sep + _hash, "r") as file:
                token = file.read()
                payload = tina4_python.tina4_auth.get_payload(token)
                for key in payload:
                    self.set(key, payload[key])
        else:
            self.start(_hash)

    def set(self, _key, _value):
        # add the key value to the file
        return True

    def get(self, _key):
        # return value
        return ""

    def close(self):
        pass
