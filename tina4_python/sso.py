"""Provider-neutral, configuration-first OpenID Connect SSO."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request as UrlRequest, urlopen


class SsoError(RuntimeError):
    """An OIDC configuration, protocol, or verification failure."""


class Sso:
    PENDING_KEY = "_tina4_sso_pending"
    SESSION_KEY = "_tina4_sso"
    _mounted = False

    def __init__(self, issuer=None, client_id=None, client_secret=None,
                 redirect_uri=None, scopes=None, verify=None,
                 post_logout_redirect_uri=None, claim_map=None, timeout=10):
        self.issuer = (issuer or os.environ.get("TINA4_SSO_ISSUER", "")).rstrip("/")
        self.client_id = client_id or os.environ.get("TINA4_SSO_CLIENT_ID", "")
        self.client_secret = client_secret if client_secret is not None else os.environ.get("TINA4_SSO_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.environ.get("TINA4_SSO_REDIRECT_URI", "")
        self.scopes = scopes or self._json_env("TINA4_SSO_SCOPES", ["openid", "profile", "email"])
        self.verify = (verify or os.environ.get("TINA4_SSO_VERIFY", "introspection")).lower()
        self.post_logout_redirect_uri = post_logout_redirect_uri or os.environ.get("TINA4_SSO_POST_LOGOUT_REDIRECT_URI")
        self.claim_map = claim_map or self._json_env("TINA4_SSO_CLAIM_MAP", {})
        self.timeout = timeout
        self.metadata = {}
        self._validate_config()

    @classmethod
    def from_issuer(cls, issuer=None, **kwargs):
        value = cls(issuer=issuer, **kwargs)
        value.discover()
        return value

    @staticmethod
    def configured():
        return all(os.environ.get(key) for key in (
            "TINA4_SSO_ISSUER", "TINA4_SSO_CLIENT_ID", "TINA4_SSO_REDIRECT_URI"
        ))

    @staticmethod
    def _json_env(name, default):
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SsoError(f"{name} must be valid JSON") from exc

    @staticmethod
    def _loopback(host):
        return host in {"localhost", "127.0.0.1", "::1"}

    @classmethod
    def _secure_url(cls, value, name):
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.hostname:
            raise SsoError(f"{name} must be an absolute URL")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and cls._loopback(parsed.hostname)):
            raise SsoError(f"{name} must use HTTPS except on loopback")

    def _validate_config(self):
        if not self.issuer or not self.client_id or not self.redirect_uri:
            raise SsoError("TINA4_SSO_ISSUER, TINA4_SSO_CLIENT_ID and TINA4_SSO_REDIRECT_URI are required")
        self._secure_url(self.issuer, "issuer")
        self._secure_url(self.redirect_uri, "redirect URI")
        if self.verify not in {"introspection", "jwks"}:
            raise SsoError("TINA4_SSO_VERIFY must be introspection or jwks")
        if self.verify == "jwks":
            raise SsoError("jwks verification requires an installed cryptography capability")
        if self.verify == "introspection" and not self.client_secret:
            raise SsoError("introspection verification requires TINA4_SSO_CLIENT_SECRET")
        if not isinstance(self.scopes, list) or "openid" not in self.scopes:
            raise SsoError("TINA4_SSO_SCOPES must be a list containing openid")

    def _request_json(self, url, form=None, bearer=None, basic=False):
        headers = {"Accept": "application/json"}
        data = None
        if form is not None:
            data = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if basic:
            raw = f"{self.client_id}:{self.client_secret}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        try:
            with urlopen(UrlRequest(url, data=data, headers=headers), timeout=self.timeout) as response:
                result = json.loads(response.read().decode())
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            raise SsoError("OIDC provider request failed") from exc
        if not isinstance(result, dict):
            raise SsoError("OIDC provider returned a non-object response")
        return result

    def discover(self, force=False):
        if self.metadata and not force:
            return dict(self.metadata)
        result = self._request_json(f"{self.issuer}/.well-known/openid-configuration")
        if result.get("issuer") != self.issuer:
            raise SsoError("OIDC discovery issuer does not exactly match configuration")
        required = ["authorization_endpoint", "token_endpoint"]
        if self.verify == "introspection":
            required.append("introspection_endpoint")
        for key in required:
            if not result.get(key):
                raise SsoError(f"OIDC discovery is missing {key}")
            self._secure_url(result[key], key)
        self.metadata = result
        return dict(result)

    @staticmethod
    def _safe_return(value):
        if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
            return "/"
        return "/" if any(ord(char) < 32 for char in value) else value

    def login(self, request_or_session, return_to="/"):
        session = getattr(request_or_session, "session", request_or_session)
        if session is None:
            raise SsoError("SSO login requires a Tina4 Session")
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        session.set(self.PENDING_KEY, {
            "state": state, "nonce": nonce, "verifier": verifier,
            "return_to": self._safe_return(return_to), "created_at": int(time.time()),
        })
        session.save()
        query = urlencode({
            "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "response_type": "code", "scope": " ".join(self.scopes),
            "state": state, "nonce": nonce, "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return f"{self.discover()['authorization_endpoint']}?{query}"

    @staticmethod
    def _jwt_payload(token):
        try:
            part = token.split(".")[1]
            return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        except (IndexError, ValueError, json.JSONDecodeError) as exc:
            raise SsoError("provider returned an invalid ID token") from exc

    def _introspect(self, access_token):
        result = self._request_json(self.discover()["introspection_endpoint"], {
            "token": access_token, "token_type_hint": "access_token"
        }, basic=True)
        if result.get("active") is not True or result.get("iss") != self.issuer:
            raise SsoError("OIDC access token is inactive or has the wrong issuer")
        audience = result.get("aud", result.get("client_id"))
        valid = self.client_id in audience if isinstance(audience, list) else audience == self.client_id
        valid = valid or result.get("client_id") == self.client_id
        if not valid:
            raise SsoError("OIDC token audience mismatch")
        return result

    @staticmethod
    def _claim(claims, path, fallback):
        value = claims
        for part in (path or fallback).split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def _normalize(self, claims):
        subject = self._claim(claims, self.claim_map.get("subject"), "sub")
        issuer = self._claim(claims, self.claim_map.get("issuer"), "iss") or self.issuer
        if not subject or issuer != self.issuer:
            raise SsoError("OIDC identity is missing a valid issuer or subject")
        roles = self._claim(claims, self.claim_map.get("roles"), "realm_access.roles") or []
        roles += (claims.get("resource_access", {}).get(self.client_id, {}) or {}).get("roles", [])
        groups = self._claim(claims, self.claim_map.get("groups"), "groups") or []
        return {
            "issuer": issuer, "subject": subject,
            "username": self._claim(claims, self.claim_map.get("username"), "preferred_username"),
            "email": self._claim(claims, self.claim_map.get("email"), "email"),
            "name": self._claim(claims, self.claim_map.get("name"), "name"),
            "roles": sorted(set(map(str, roles))), "groups": sorted(set(map(str, groups))),
        }

    def callback(self, request_or_session, query=None):
        session = getattr(request_or_session, "session", request_or_session)
        query = query if query is not None else getattr(request_or_session, "query", {})
        pending = session.get(self.PENDING_KEY) if session else None
        if session:
            session.delete(self.PENDING_KEY)
        state, code = str(query.get("state", "")), str(query.get("code", ""))
        if not isinstance(pending, dict) or not code or not hmac.compare_digest(state, str(pending.get("state", ""))):
            raise SsoError("OIDC callback state is invalid or already consumed")
        if int(time.time()) - int(pending.get("created_at", 0)) > 600:
            raise SsoError("OIDC callback state has expired")
        tokens = self._request_json(self.discover()["token_endpoint"], {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": self.redirect_uri, "client_id": self.client_id,
            "code_verifier": pending["verifier"],
        }, basic=bool(self.client_secret))
        access_token, id_token = tokens.get("access_token"), tokens.get("id_token")
        if not access_token or not id_token:
            raise SsoError("OIDC token response is incomplete")
        if self.verify == "jwks":
            raise SsoError("JWKS verification requires an installed cryptography capability")
        claims = self._introspect(access_token)
        if not hmac.compare_digest(str(self._jwt_payload(id_token).get("nonce", "")), str(pending.get("nonce", ""))):
            raise SsoError("OIDC ID token nonce mismatch")
        if self.discover().get("userinfo_endpoint"):
            claims.update(self._request_json(self.discover()["userinfo_endpoint"], bearer=access_token))
        identity = self._normalize(claims)
        session.regenerate()
        session.set(self.SESSION_KEY, {
            "version": 1, "identity": identity, "access_token": access_token,
            "refresh_token": tokens.get("refresh_token"), "id_token": id_token,
            "expires_at": int(time.time()) + int(tokens.get("expires_in", 0)),
        })
        return {"identity": identity, "return_to": self._safe_return(pending.get("return_to"))}

    def identity(self, request_or_session):
        session = getattr(request_or_session, "session", request_or_session)
        stored = session.get(self.SESSION_KEY) if session else None
        identity = stored.get("identity") if isinstance(stored, dict) else None
        if identity is not None and hasattr(request_or_session, "user"):
            request_or_session.user = identity
        return identity

    def refresh(self, request_or_session):
        session = getattr(request_or_session, "session", request_or_session)
        stored = session.get(self.SESSION_KEY) if session else None
        refresh_token = stored.get("refresh_token") if isinstance(stored, dict) else None
        if not refresh_token:
            if session:
                session.delete(self.SESSION_KEY)
            raise SsoError("OIDC session cannot be refreshed")
        try:
            tokens = self._request_json(self.discover()["token_endpoint"], {
                "grant_type": "refresh_token", "refresh_token": refresh_token,
                "client_id": self.client_id,
            }, basic=bool(self.client_secret))
            access_token = tokens.get("access_token")
            claims = self._introspect(access_token)
            if self.discover().get("userinfo_endpoint"):
                claims.update(self._request_json(self.discover()["userinfo_endpoint"], bearer=access_token))
            identity = self._normalize(claims)
            stored.update({
                "identity": identity, "access_token": access_token,
                "refresh_token": tokens.get("refresh_token") or refresh_token,
                "id_token": tokens.get("id_token") or stored.get("id_token"),
                "expires_at": int(time.time()) + int(tokens.get("expires_in", 0)),
            })
            session.set(self.SESSION_KEY, stored)
            return identity
        except Exception:
            session.delete(self.SESSION_KEY)
            raise

    def logout(self, request_or_session, return_to="/"):
        session = getattr(request_or_session, "session", request_or_session)
        stored = session.get(self.SESSION_KEY) if session else {}
        id_token = stored.get("id_token") if isinstance(stored, dict) else None
        if session:
            session.destroy()
        endpoint = self.discover().get("end_session_endpoint")
        target = self.post_logout_redirect_uri or self._safe_return(return_to)
        if not endpoint:
            return target
        params = {"post_logout_redirect_uri": target, "client_id": self.client_id}
        if id_token:
            params["id_token_hint"] = id_token
        return f"{endpoint}?{urlencode(params)}"

    @classmethod
    def mount_configured(cls):
        """Mount the canonical routes when SSO configuration is present."""
        if cls._mounted or not cls.configured():
            return False
        from tina4_python.core.router import Router

        owned = {("GET", "/auth/login"), ("GET", "/auth/callback"), ("POST", "/auth/logout")}
        collisions = [
            f"{route['method']} {route['path']}" for route in Router.get_routes()
            if (route["method"], route["path"]) in owned
        ]
        if collisions:
            raise SsoError("SSO route collision: " + ", ".join(collisions))
        sso = cls.from_issuer()

        def login_route(request, response):
            return response.redirect(sso.login(request, request.query.get("return_to", "/")))

        def callback_route(request, response):
            try:
                return response.redirect(sso.callback(request)["return_to"])
            except SsoError as exc:
                return response.error("SSO_CALLBACK_FAILED", str(exc), 400)

        def logout_route(request, response):
            return response.redirect(sso.logout(request, request.query.get("return_to", "/")))

        Router.add("GET", "/auth/login", login_route, auth_required=False)
        Router.add("GET", "/auth/callback", callback_route, auth_required=False)
        Router.add("POST", "/auth/logout", logout_route, auth_required=True)
        cls._mounted = True
        return True


SSO = Sso
