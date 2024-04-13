#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os
from http import cookies
import hashlib
import tina4_python
from tina4_python.Debug import Debug
from tina4_python import Constant


class Session:

    def __init__(self, _default_name="PY_SESS", _default_path="sessions"):
        self.session_name = _default_name
        self.cookie = cookies.SimpleCookie()
        self.session_path = _default_path
        self.session_values = {}
        self.session_hash = ""

    def start(self, _hash=None):
        # create a file for the session?
        # set the cookie for the session
        token = tina4_python.tina4_auth.get_token(payload_data=self.session_values)
        if _hash is None:
            file_hash = hashlib.md5(token.encode()).hexdigest()
            self.save()
        else:
            file_hash = _hash
        self.session_hash = file_hash

        return file_hash

    def load(self, _hash):
        """
        Loads a session based on the hash
        :param _hash:
        :return:
        """
        self.session_hash = _hash
        if os.path.isfile(self.session_path + os.sep + _hash):
            with open(self.session_path + os.sep + _hash, "r") as file:
                token = file.read()
                file.close()
                if tina4_python.tina4_auth.valid(token):
                    payload = tina4_python.tina4_auth.get_payload(token)
                    for key in payload:
                        if key != "expires":
                            self.set(key, payload[key])
                else:
                    Debug("Session expired, starting a new one", Constant.TINA4_LOG_DEBUG)
                    self.start(_hash)
        else:
            Debug("Cannot load session, starting a new one", Constant.TINA4_LOG_DEBUG)
            self.start(_hash)

    def set(self, _key, _value):
        """
        Sets a session key value
        :param _key:
        :param _value:
        :return:
        """
        self.session_values[_key] = _value
        self.save()
        return True

    def unset(self, _key):
        """
        Unsets the session key
        :param _key:
        :return:
        """
        if _key in self.session_values:
            del self.session_values[_key]
            self.save()
            return True
        else:
            return False

    def get(self, _key):
        """
        Returns false if session cannot be retrieved
        :param _key:
        :return:
        """
        if _key in self.session_values:
            return self.session_values[_key]
        else:
            return None

    def close(self):
        if os.path.isfile(self.session_path + os.sep + self.session_hash):
            os.remove(self.session_path + os.sep + self.session_hash)

    def save(self):
        """
        Saves the session information
        :return:
        """
        try:
            if not os.path.exists(self.session_path):
                os.makedirs(self.session_path)
            Debug("SAVING", self.session_values, self.session_path, Constant.TINA4_LOG_DEBUG)
            token = tina4_python.tina4_auth.get_token(payload_data=self.session_values)
            with open(self.session_path + os.sep + self.session_hash, "w") as file:
                file.write(token)
                file.close()
                return True
        except Exception as E:
            Debug("Session save failure", E, Constant.TINA4_LOG_ERROR)
            return False
