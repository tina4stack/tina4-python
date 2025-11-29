#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os
from http import cookies
import sys
import importlib
import hashlib
import tina4_python
from tina4_python.Debug import Debug
from tina4_python import Constant

class SessionHandler(object):
    """
    Base class for session handling.
    """

    @staticmethod
    def load(session, _hash):
        pass

    @staticmethod
    def set(session, _key, _value):
        try:
            session.session_values[_key] = _value
            session.save()
            return True
        except Exception:
            return False

    @staticmethod
    def unset(session, _key):
        if _key in session.session_values:
            del session.session_values[_key]
            session.save()
            return True
        else:
            return False

    @staticmethod
    def get(session, _key):
        if _key in session.session_values:
            return session.session_values[_key]
        else:
            return None

    @staticmethod
    def close(session):
        pass

    @staticmethod
    def save(session):
        pass

class SessionFileHandler(SessionHandler):
    """
    Session File Handler
    """
    @staticmethod
    def load(session, _hash):
        session.session_hash = _hash
        if os.path.isfile(session.session_path + os.sep + _hash):
            with open(session.session_path + os.sep + _hash, "r") as file:
                token = file.read()
                file.close()
                if tina4_python.tina4_auth.valid(token):
                    payload = tina4_python.tina4_auth.get_payload(token)
                    for key in payload:
                        if key != "expires":
                            session.set(key, payload[key])
                else:
                    Debug.debug("Session expired, starting a new one")
                    session.start(_hash)
        else:
            Debug.debug("Cannot load session, starting a new one")
            session.start(_hash)

    @staticmethod
    def close(session):
        try:
            if os.path.isfile(session.session_path + os.sep + session.session_hash):
                os.remove(session.session_path + os.sep + session.session_hash)
            return True
        except Exception:
            return False

    @staticmethod
    def save(session):
        try:
            if not os.path.exists(session.session_path):
                os.makedirs(session.session_path)
            token = tina4_python.tina4_auth.get_token(payload_data=session.session_values)
            with open(session.session_path + os.sep + session.session_hash, "w") as file:
                file.write(token)
                file.close()
                return True
        except Exception as e:
            Debug.error("Session save failure", e)
            return False

class SessionRedisHandler(SessionHandler):

    @staticmethod
    def __init_redis():
        try:
            redis = importlib.import_module("redis")
        except Exception as e:
            Debug.error("Redis not installed, install with pip install redis or poetry add redis", str(e))
            sys.exit(1)

        if os.getenv("TINA4_SESSION_REDIS_SECRET", "") != "":
            redis_instance = redis.Redis(host=os.getenv("TINA4_SESSION_REDIS_HOST", "localhost"),
                                         port=os.getenv("TINA4_SESSION_REDIS_PORT",6379),
                                         password=os.getenv("TINA4_SESSION_REDIS_SECRET", ""),
                                         decode_responses=True)
        else:
            redis_instance = redis.Redis(host=os.getenv("TINA4_SESSION_REDIS_HOST", "localhost"),
                                         port=os.getenv("TINA4_SESSION_REDIS_PORT",6379),
                                         decode_responses=True)
        return redis_instance

    """
    Session Redis Handler
    """
    @staticmethod
    def load(session, _hash):
        """
        Loads the redis session
        :param session:
        :param _hash:
        :return:
        """
        try:
            session.session_hash = _hash
            r = SessionRedisHandler.__init_redis()
            token = r.get(_hash)
            if tina4_python.tina4_auth.valid(token):
                payload = tina4_python.tina4_auth.get_payload(token)
                for key in payload:
                    if key != "expires":
                        session.set(key, payload[key])
            else:
                Debug.warning("Session expired, starting a new one")
                _hash = None
                session.start(_hash)
        except Exception as e:
            Debug.error("Redis not available, sessions will fail", e)


    @staticmethod
    def close(session):
        """
        Closes the redis session
        :param session:
        :return:
        """
        r = SessionRedisHandler.__init_redis()
        try:
            r.set(session.session_hash, "")
            return True
        except Exception:
            return False

    @staticmethod
    def save(session):
        """
        Saves the redis session
        :param session:
        :return:
        """
        r = SessionRedisHandler.__init_redis()
        try:
            token = tina4_python.tina4_auth.get_token(payload_data=session.session_values)
            r.set(session.session_hash, token)
            return True
        except Exception as e:
            Debug.error("Session save failure", str(e))
            return False

class SessionValkeyHandler(SessionHandler):

    @staticmethod
    def __init_valkey():
        try:
            valkey = importlib.import_module("valkey")
        except Exception as e:
            Debug.error("Valkey not installed, install with pip/uv", str(e))
            sys.exit(1)

        params = {
            "host": os.getenv("TINA4_SESSION_VALKEY_HOST", "localhost"),
            "port": int(os.getenv("TINA4_SESSION_VALKEY_PORT", 6379)),
            "decode_responses": True
        }
        if os.getenv("TINA4_SESSION_VALKEY_SECRET", ""):
            params["password"] = os.getenv("TINA4_SESSION_VALKEY_SECRET", "")
            params["username"] = os.getenv("TINA4_SESSION_VALKEY_USER", "default")

        if os.getenv("TINA4_SESSION_VALKEY_SSL", "False").upper() == "TRUE":
            params["ssl"] = True

        valkey_instance = valkey.Valkey(**params)

        return valkey_instance

    """
    Session Valkey Handler
    """
    @staticmethod
    def load(session, _hash):
        """
        Loads the Valkey session
        :param session:
        :param _hash:
        :return:
        """
        try:
            session.session_hash = _hash
            r = SessionValkeyHandler.__init_valkey()
            token = r.get(_hash)
            if tina4_python.tina4_auth.valid(token):
                payload = tina4_python.tina4_auth.get_payload(token)
                for key in payload:
                    if key != "expires":
                        session.set(key, payload[key])
            else:
                Debug.error("Session expired, starting a new one")
                session.start(_hash)
        except Exception as e:
            Debug.error("Valkey not available, sessions will fail", str(e))


    @staticmethod
    def close(session):
        """
        Closes the Valkey session
        :param session:
        :return:
        """
        r = SessionValkeyHandler.__init_valkey()
        try:
            r.set(session.session_hash, "")
            return True
        except Exception:
            return False

    @staticmethod
    def save(session):
        """
        Saves the Valkey session
        :param session:
        :return:
        """
        r = SessionValkeyHandler.__init_valkey()
        try:
            token = tina4_python.tina4_auth.get_token(payload_data=session.session_values)
            r.set(session.session_hash, token)
            return True
        except Exception as e:
            Debug.error("Session save failure", str(e))
            return False

class Session:

    def __init__(self, _default_name="PY_SESS", _default_path="sessions", _default_handler="SessionFileHandler"):
        self.session_name = _default_name
        self.cookie = cookies.SimpleCookie()
        self.session_path = _default_path
        self.session_values = {}
        self.session_hash = ""
        self.default_handler = _default_handler
        exec("self.default_handler = "+_default_handler)

    def start(self, _hash=None):
        # create a file for the session?
        # set the cookie for the session
        token = tina4_python.tina4_auth.get_token(payload_data=self.session_values)
        if _hash is None:
            file_hash = hashlib.md5(token.encode()).hexdigest()
        else:
            file_hash = _hash
        self.session_hash = file_hash
        self.save()

        return file_hash

    def load(self, _hash):
        """
        Loads a session based on the hash
        :param _hash:
        :return:
        """
        self.default_handler.load(self, _hash)

    def set(self, _key, _value):
        """
        Sets a session key value
        :param _key:
        :param _value:
        :return:
        """
        return self.default_handler.set(self, _key, _value)


    def unset(self, _key):
        """
        Unsets the session key
        :param _key:
        :return:
        """
        return self.default_handler.unset(self, _key)

    def get(self, _key):
        """
        Returns false if session cannot be retrieved
        :param _key:
        :return:
        """
        return self.default_handler.get(self, _key)

    def close(self):
        """
        Close the session and remove the file or record
        :return:
        """
        return self.default_handler.close(self)

    def save(self):
        """
        Saves the session information
        :return:
        """
        return self.default_handler.save(self)

    def __iter__(self):
        for key, value in self.session_values.items():
            if key != "expires":
                yield key, value

