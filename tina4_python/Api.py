#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501

import json
from typing import Optional, Dict, Any, Union, List

import requests
from requests.auth import HTTPBasicAuth


class Api:
    """
    Consume REST API interfaces with minimal code - Tina4 style.

    Lightweight wrapper around `requests` providing:
    - Base URL handling
    - Bearer token or custom auth header
    - Basic authentication
    - Persistent and per-request custom headers
    - Automatic JSON serialization
    - SSL verification control
    - Consistent response dictionary

    """

    def __init__(
            self,
            base_url: Optional[str] = None,
            auth_header: str = "",
            ignore_ssl_validation: bool = False,
    ):
        """
        Initialize the API client.

        Args:
            base_url (str, optional): Root URL of the API (trailing slash is stripped)
            auth_header (str): Full authentication header, e.g. "Authorization: Bearer xyz"
            ignore_ssl_validation (bool): Disable SSL certificate verification when True
        """
        self.base_url = base_url.rstrip("/") if base_url else None
        self.auth_header = auth_header.strip()
        self.ignore_ssl_validation = ignore_ssl_validation

        self.custom_headers: List[str] = []          # persistent custom headers
        self.username: Optional[str] = None          # for Basic Auth
        self.password: Optional[str] = None          # for Basic Auth

    def add_custom_headers(self, headers: Union[Dict[str, str], List[str]]) -> None:
        """
        Add persistent headers that are sent with every request.

        Args:
            headers: Dictionary of headers or list of "Key: Value" strings
        """
        if isinstance(headers, dict):
            self.custom_headers.extend(f"{k}: {v}" for k, v in headers.items())
        else:
            self.custom_headers.extend(headers)

    def set_username_password(self, username: str, password: str) -> None:
        """
        Set credentials for HTTP Basic Authentication.

        Args:
            username: Username or client id
            password: Password or secret
        """
        self.username = username
        self.password = password

    def send_request(
            self,
            rest_service: str = "",
            request_type: str = "GET",
            body: Optional[Any] = None,
            content_type: str = "application/json",
            custom_headers: Optional[Dict[str, str]] = None,
            timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Execute an HTTP request against the API.

        Args:
            rest_service (str): Endpoint path (appended to base_url)
            request_type (str): HTTP method - GET, POST, PUT, PATCH, DELETE, etc.
            body (any, optional): Request payload (auto JSON-encoded when content_type is JSON)
            content_type (str): Value for the Content-Type header
            custom_headers (dict, optional): One-time headers for this request only
            timeout (int): Request timeout in seconds

        Returns:
            dict containing:
                - http_code (int): HTTP status code
                - body (dict|list|str): Parsed JSON when possible, otherwise raw text
                - headers (dict): Response headers
                - error (str|None): Error message if the request failed
        """
        if custom_headers is None:
            custom_headers = {}

        url = f"{self.base_url}{rest_service}" if self.base_url else rest_service

        # Base headers
        headers = {
            "Accept": content_type,
            "Accept-Charset": "utf-8, *;q=0.8",
        }

        # Persistent custom headers
        for header in self.custom_headers:
            if ":" in header:
                key, value = header.split(":", 1)
                headers[key.strip()] = value.strip()

        # One-time custom headers
        headers.update(custom_headers)

        # Authentication
        auth = None
        if self.username and self.password:
            auth = HTTPBasicAuth(self.username, self.password)
        elif self.auth_header:
            parts = self.auth_header.split(":", 1)
            if len(parts) == 2:
                key, val = parts
                headers[key.strip()] = val.strip()
            else:
                # Fallback for "Bearer xyz" style
                header_parts = self.auth_header.split()
                if len(header_parts) >= 2:
                    headers[header_parts[0]] = " ".join(header_parts[1:])

        # Payload handling
        json_payload = None
        data_payload = None
        if body is not None:
            if content_type == "application/json" and isinstance(body, (dict, list)):
                json_payload = body
                headers["Content-Type"] = content_type
            else:
                data_payload = body if isinstance(body, (str, bytes)) else str(body)
                headers["Content-Type"] = content_type

        try:
            response = requests.request(
                method=request_type.upper(),
                url=url,
                headers=headers,
                json=json_payload,
                data=data_payload,
                auth=auth,
                verify=not self.ignore_ssl_validation,
                timeout=timeout,
            )

            # Parse JSON if possible
            try:
                parsed_body = response.json()
            except json.JSONDecodeError:
                parsed_body = response.text

            return {
                "http_code": response.status_code,
                "body": parsed_body,
                "headers": dict(response.headers),
                "error": None,
            }

        except requests.RequestException as e:
            return {
                "http_code": None,
                "body": None,
                "headers": {},
                "error": str(e),
            }
