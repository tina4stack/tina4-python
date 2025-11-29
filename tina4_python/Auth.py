#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import datetime
import os
import jwt
import bcrypt
from json import JSONEncoder
from cryptography import x509
from cryptography.x509 import NameOID
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

class AuthJSONSerializer(JSONEncoder):
    """
    Custom JSON encoder used by PyJWT when serializing payload objects.

    Ensures that ``datetime.datetime`` instances are correctly converted to ISO-8601
    strings so they can be embedded in JWT claims.
    """

    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        return super().default(o)


class Auth:
    """
    Authentication & authorization helper for Tina4 projects.

    Handles:
      - Password hashing/verification (bcrypt)
      - Automatic creation and loading of an RSA private/public key pair
      - Self-signed certificate generation for local HTTPS development
      - Signing JWT tokens with RS256 (private key)
      - Verifying JWT tokens with RS256 (public key)
      - Simple API-KEY fallback validation

    Keys and certificates are stored in ``<root_path>/secrets/``:
        - private.key   → encrypted PEM private key
        - public.key    → PEM public key (unencrypted)
        - domain.cert   → self-signed certificate (for local dev servers)

    Environment variables used:
        - ``SECRET``            → passphrase used to encrypt the private key
        - ``API_KEY``           → optional static API key (checked before JWT)
        - ``TINA4_TOKEN_LIMIT`` → default token lifetime in minutes (default: 2)
        - Country/State/City/Organization/Domain variables for the cert
    """

    # ------------------------------------------------------------------
    # Class-level attributes (set in __init__)
    # ------------------------------------------------------------------
    secret: str | None = None          # Passphrase for private key encryption
    private_key: str = None            # Path to encrypted private key file
    public_key: str = None             # Path to public key file
    self_signed: str = None            # Path to self-signed cert file
    root_path: str = None              # Project root directory

    # Cached key objects (avoid reloading from disk on every request)
    loaded_private_key = None
    loaded_public_key = None

    # ------------------------------------------------------------------
    # Password handling (bcrypt)
    # ------------------------------------------------------------------
    def hash_password(self, text: str) -> str:
        """
        Generate a bcrypt hash for the given plain-text password.

        Args:
            text (str): Plain-text password.

        Returns:
            str: bcrypt hash (as UTF-8 string). Safe to store in a database.
        """
        password_bytes = text.encode("utf-8")
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password_bytes, salt).decode("utf-8")

    def check_password(self, password_hash: str, text: str) -> bool:
        """
        Verify a plain-text password against a previously created bcrypt hash.

        Args:
            password_hash (str): Hash returned by :meth:`hash_password`.
            text (str): Plain-text password to verify.

        Returns:
            bool: ``True`` if the password matches the hash.
        """
        password_bytes = text.encode("utf-8")
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))

    # ------------------------------------------------------------------
    # Private / public key loading (with caching)
    # ------------------------------------------------------------------
    def load_private_key(self):
        """
        Load (and cache) the RSA private key from ``secrets/private.key``.

        The key is encrypted with the passphrase stored in ``self.secret``
        (which comes from the environment variable ``SECRET``).

        Returns:
            cryptography.hazmat.primitives.asymmetric.rsa.RSAPrivateKey
        """
        if self.loaded_private_key:
            return self.loaded_private_key

        with open(self.private_key, "rb") as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=self.secret.encode(),
                backend=default_backend(),
            )
            self.loaded_private_key = private_key
            return private_key

    def load_public_key(self):
        """
        Load (and cache) the RSA public key from ``secrets/public.key``.

        Returns:
            cryptography.hazmat.primitives.asymmetric.rsa.RSAPublicKey
        """
        if self.loaded_public_key:
            return self.loaded_public_key

        with open(self.public_key, "rb") as f:
            public_key = serialization.load_pem_public_key(
                f.read(), backend=default_backend()
            )
            self.loaded_public_key = public_key
            return public_key

    # ------------------------------------------------------------------
    # Constructor – creates secrets folder & keys if missing
    # ------------------------------------------------------------------
    def __init__(self, root_path: str):
        """
        Initialise the Auth helper and ensure cryptographic material exists.

        Args:
            root_path (str): Absolute path to the project root (where the
                             ``secrets`` folder will be created).
        """
        self.root_path = root_path
        self.secret = os.environ.get("SECRET", "{self.secret}")
        self.private_key = os.path.join(root_path, "secrets", "private.key")
        self.public_key = os.path.join(root_path, "secrets", "public.key")
        self.self_signed = os.path.join(root_path, "secrets", "domain.cert")

        # Ensure secrets directory exists
        os.makedirs(os.path.join(root_path, "secrets"), exist_ok=True)

        # ------------------------------------------------------------------
        # 1. Private key – generate if missing
        # ------------------------------------------------------------------
        if not os.path.isfile(self.private_key):
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            with open(self.private_key, "wb") as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.BestAvailableEncryption(self.secret.encode()),
                ))
        else:
            private_key = self.load_private_key()

        # ------------------------------------------------------------------
        # 2. Public key – derive from private key if missing
        # ------------------------------------------------------------------
        if not os.path.isfile(self.public_key):
            public_key = private_key.public_key()
            public_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            with open(self.public_key, "wb") as f:
                f.write(public_pem)

        # ------------------------------------------------------------------
        # 3. Self-signed certificate (useful for local HTTPS servers)
        # ------------------------------------------------------------------
        if not os.path.isfile(self.self_signed):
            subject = issuer = x509.Name(
                [
                    x509.NameAttribute(NameOID.COUNTRY_NAME, os.environ.get("COUNTRY", "ZA")),
                    x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, os.environ.get("STATE", "WESTERN CAPE")),
                    x509.NameAttribute(NameOID.LOCALITY_NAME, os.environ.get("CITY", "CAPE TOWN")),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, os.environ.get("ORGANIZATION", "Tina4")),
                    x509.NameAttribute(NameOID.COMMON_NAME, os.environ.get("DOMAIN_NAME", "localhost")),
                ]
            )
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
                .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=99999))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                .sign(private_key, hashes.SHA256())
            )

            with open(self.self_signed, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))

    # ------------------------------------------------------------------
    # JWT creation & verification
    # ------------------------------------------------------------------
    def get_token(self, payload_data: dict, expiry_minutes: int = 0) -> str:
        """
        Create a signed JWT (RS256) containing the supplied payload.

        If ``expires`` is not present in ``payload_data`` an expiration claim
        will be added automatically using ``TINA4_TOKEN_LIMIT`` (default 2 minutes)
        or the value supplied via ``expiry_minutes``.

        Args:
            payload_data (dict): Claims to embed in the token.
            expiry_minutes (int): Override default token lifetime (0 = use env default).

        Returns:
            str: Signed JWT (compact serialization).
        """
        private_key = self.load_private_key()
        now = datetime.datetime.now(datetime.timezone.utc)

        if "expires" not in payload_data:
            token_limit_minutes = int(os.environ.get("TINA4_TOKEN_LIMIT", 2))
            if expiry_minutes != 0:
                token_limit_minutes = expiry_minutes
            expiry_time = now + datetime.timedelta(minutes=token_limit_minutes)
            payload_data["expires"] = expiry_time.isoformat()

        token = jwt.encode(
            payload=payload_data,
            key=private_key,
            algorithm="RS256",
            json_encoder=AuthJSONSerializer,
        )
        return token

    def get_payload(self, token: str) -> dict | None:
        """
        Decode a JWT and return its payload (without verification of expiry).

        Used when you only need the claims and will perform your own validation.

        Args:
            token (str): JWT to decode.

        Returns:
            dict | None: Payload dictionary or ``None`` on invalid signature.
        """
        public_key = self.load_public_key()
        try:
            payload = jwt.decode(token, key=public_key, algorithms=["RS256"])
            return payload
        except jwt.InvalidSignatureError:
            return None

    def validate(self, token: str) -> bool:
        """
        Full token validation.

        Checks:
          1. Optional static ``API_KEY`` environment variable (quick bypass)
          2. RS256 signature using the public key
          3. Presence and validity of the ``expires`` claim

        Args:
            token (str): Bearer token.

        Returns:
            bool: ``True`` if the token is valid and not expired.
        """
        # Simple API-KEY fallback (useful for quick internal scripts)
        if os.environ.get("API_KEY") and token == os.environ.get("API_KEY"):
            return True

        public_key = self.load_public_key()
        try:
            payload = jwt.decode(token, key=public_key, algorithms=["RS256"])

            if "expires" not in payload:
                return False

            expiry_time = datetime.datetime.fromisoformat(payload["expires"])
            if expiry_time.tzinfo is None:
                # Treat naive datetime as UTC for backward compatibility
                expiry_time = expiry_time.replace(tzinfo=datetime.timezone.utc)

            return datetime.datetime.now(datetime.timezone.utc) <= expiry_time

        except Exception:  # noqa: BLE001 – we intentionally catch everything here
            return False

    # ------------------------------------------------------------------
    # Alias for backward compatibility
    # ------------------------------------------------------------------
    def valid(self, token: str) -> bool:
        """
        Alias of :meth:`validate`. Kept for older codebases.

        Args:
            token (str): Bearer token.

        Returns:
            bool: ``True`` if token is valid.
        """
        return self.validate(token)