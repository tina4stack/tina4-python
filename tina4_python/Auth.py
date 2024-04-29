#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import datetime
import os

import jwt
from cryptography import x509
from cryptography.x509 import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


class Auth:
    secret = None
    private_key = None
    root_path = None
    loaded_private_key = None
    loaded_public_key = None

    def load_private_key(self):
        if self.loaded_private_key:
            return self.loaded_private_key
        with open(self.private_key, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(), b"{self.secret}", backend=default_backend()
            )
            self.loaded_private_key = private_key
            return private_key

    def load_public_key(self):
        if self.loaded_public_key:
            return self.loaded_public_key
        with open(self.public_key, "rb") as f:
            public_key = serialization.load_pem_public_key(
                f.read(), backend=default_backend()
            )
            self.loaded_public_key = public_key
            return public_key

    def __init__(self, root_path):
        self.root_path = root_path
        self.secret = os.environ.get("SECRET", None)
        self.private_key = root_path + os.sep + "secrets" + os.sep + "private.key"
        self.public_key = root_path + os.sep + "secrets" + os.sep + "public.key"
        self.self_signed = root_path + os.sep + "secrets" + os.sep + "domain.cert"

        # check if we have a secrets folder
        if not os.path.exists(root_path + os.sep + "secrets"):
            os.makedirs(root_path + os.sep + "secrets")

        if not os.path.isfile(self.private_key):
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            with open(self.private_key, "wb") as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.BestAvailableEncryption(b"{self.secret}"),
                ))
        else:
            private_key = self.load_private_key()

        if not os.path.isfile(self.public_key):
            public_key = private_key.public_key()
            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            with open(self.public_key, 'wb') as f:
                f.write(public_pem)

        if not os.path.isfile(self.self_signed):
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, os.environ.get('COUNTRY', 'ZA')),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, os.environ.get('STATE', 'WESTERN CAPE')),
                x509.NameAttribute(NameOID.LOCALITY_NAME, os.environ.get('CITY', 'CAPE TOWN')),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, os.environ.get('ORGANIZATION', 'Tina4')),
                x509.NameAttribute(NameOID.COMMON_NAME, os.environ.get('DOMAIN_NAME', 'localhost'))
            ])
            cert = (x509.CertificateBuilder().subject_name(
                subject
            ).issuer_name(
                issuer
            ).public_key(
                private_key.public_key()
            ).serial_number(
                x509.random_serial_number()
            ).not_valid_before(
                datetime.datetime.now(datetime.timezone.utc)
            ).not_valid_after(
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=99999)
            ).add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]),
                critical=False,
            ).sign(private_key, hashes.SHA256()))

            with open(self.self_signed, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))

    def get_token(self, payload_data):
        private_key = self.load_private_key()
        now = datetime.datetime.now()
        token_limit_minutes = int(os.environ.get("TINA4_TOKEN_LIMIT", 2))
        expiry_time = now + datetime.timedelta(minutes=token_limit_minutes)
        payload_data["expires"] = expiry_time.isoformat()
        token = jwt.encode(
            payload=payload_data,
            key=private_key,
            algorithm='RS256'
        )

        return token

    def get_payload(self, token):
        public_key = self.load_public_key()
        try:
            payload = jwt.decode(token, key=public_key, algorithms=['RS256'])
        except jwt.exceptions.InvalidSignatureError:
            payload = None

        return payload

    def validate(self, token):
        # first check for API_KEY = token, simplest form
        if os.environ.get("API_KEY", None) is not None:
            if token == os.environ.get("API_KEY"):
                return True

        public_key = self.load_public_key()
        try:
            payload = jwt.decode(token, key=public_key, algorithms=['RS256'])
            if "expires" not in payload:
                return False

            if "expires" in payload:
                now = datetime.datetime.now()
                expiry_time = datetime.datetime.fromisoformat(payload["expires"])
                if now > expiry_time:
                    return False
                else:
                    return True
        except Exception:
            return False

        return False

    def valid(self, token):
        return self.validate(token)
