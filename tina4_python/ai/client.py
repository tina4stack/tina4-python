"""Zero-dependency app-facing AI client (ADR-0053)."""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse


class AiError(RuntimeError):
    """Base error for the app-facing AI client."""


class AiConfigError(AiError):
    """Invalid or incomplete AI client configuration."""


class AiHTTPError(AiError):
    """Provider or transport failure with no usable response."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AiTimeoutError(AiError):
    """The connection or total request deadline expired."""


class AiParseError(AiError):
    """A successful provider response did not satisfy its wire contract."""


@dataclass(frozen=True)
class ChatResponse:
    text: str
    model: str
    usage: dict[str, int]
    finish_reason: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class _Config:
    provider: str
    url: str
    model: str
    key: str | None
    total_timeout: float
    connect_timeout: float
    max_retries: int


class _TransportResponse:
    def __init__(self, connection: http.client.HTTPConnection, response: http.client.HTTPResponse):
        self.connection = connection
        self.response = response

    def close(self) -> None:
        try:
            self.response.close()
        finally:
            self.connection.close()


class Ai:
    """Provider-neutral AI calls configured through ``TINA4_AI_*``.

    Methods are static so the smallest useful form stays ``Ai.chat(...)``.
    Explicit call options beat environment values, which beat defaults.
    """

    _PROVIDERS = {"local", "openai", "anthropic"}

    @staticmethod
    def chat(
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        timeout: float | None = None,
        provider: str | None = None,
    ) -> ChatResponse | Iterator[str]:
        Ai._validate_messages(messages)
        config = Ai._config("chat", model=model, timeout=timeout, provider=provider)
        body = Ai._chat_body(config, messages, temperature, max_tokens, stream)
        headers = Ai._headers(config)
        if stream:
            return Ai._stream(config, headers, body)
        raw = Ai._request_json(config, headers, body)
        return Ai._normalize_chat(config.provider, raw)

    @staticmethod
    def complete(prompt: str, **options: Any) -> str:
        if not isinstance(prompt, str):
            raise AiConfigError("AI prompt must be a string")
        options.pop("stream", None)
        response = Ai.chat([{"role": "user", "content": prompt}], stream=False, **options)
        assert isinstance(response, ChatResponse)
        return response.text

    @staticmethod
    def embed(
        text_or_texts: str | list[str],
        *,
        model: str | None = None,
        timeout: float | None = None,
        provider: str | None = None,
    ) -> list[float] | list[list[float]]:
        single = isinstance(text_or_texts, str)
        if not single and not (
            isinstance(text_or_texts, list)
            and text_or_texts
            and all(isinstance(item, str) for item in text_or_texts)
        ):
            raise AiConfigError("AI embedding input must be a string or a non-empty list of strings")
        config = Ai._config("embed", model=model, timeout=timeout, provider=provider)
        if config.provider == "anthropic":
            raise AiConfigError("Anthropic does not provide the embedding endpoint in this contract")
        body = {"model": config.model, "input": text_or_texts}
        raw = Ai._request_json(config, Ai._headers(config), body)
        try:
            ordered = sorted(raw["data"], key=lambda item: item.get("index", 0))
            vectors = [item["embedding"] for item in ordered]
            if not vectors or not all(
                isinstance(vector, list)
                and vector
                and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in vector)
                for vector in vectors
            ):
                raise ValueError
            expected = 1 if single else len(text_or_texts)
            if len(vectors) != expected:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise AiParseError("AI provider returned a malformed embedding response") from None
        return vectors[0] if single else vectors

    @staticmethod
    def _validate_messages(messages: list[dict[str, Any]]) -> None:
        if not isinstance(messages, list) or not messages:
            raise AiConfigError("AI messages must be a non-empty list")
        for message in messages:
            if not isinstance(message, dict):
                raise AiConfigError("Each AI message must be an object")
            if message.get("role") not in {"system", "user", "assistant"}:
                raise AiConfigError("Each AI message needs a supported role")
            if not isinstance(message.get("content"), str):
                raise AiConfigError("Each AI message needs string content")

    @staticmethod
    def _number(name: str, default: str, *, minimum: float, integer: bool = False) -> float | int:
        raw = os.environ.get(name, default)
        try:
            value = int(raw) if integer else float(raw)
        except (TypeError, ValueError):
            raise AiConfigError(f"{name} must be numeric") from None
        if value < minimum:
            raise AiConfigError(f"{name} must be at least {minimum:g}")
        return value

    @staticmethod
    def _config(capability: str, *, model: str | None, timeout: float | None, provider: str | None) -> _Config:
        selected = (provider or os.environ.get("TINA4_AI_PROVIDER") or "local").strip().lower()
        if selected not in Ai._PROVIDERS:
            raise AiConfigError("TINA4_AI_PROVIDER must be local, openai, or anthropic")
        key = os.environ.get("TINA4_AI_KEY") or None
        if selected in {"openai", "anthropic"} and not key:
            raise AiConfigError(f"TINA4_AI_KEY is required for the {selected} provider")

        defaults = {
            "local": ("http://localhost:11437", "llama3.2"),
            "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
            "anthropic": ("https://api.anthropic.com/v1", "claude-3-5-haiku-latest"),
        }
        base, default_model = defaults[selected]
        if capability == "embed" and os.environ.get("TINA4_EMBED_URL"):
            url = os.environ["TINA4_EMBED_URL"]
        else:
            url = os.environ.get("TINA4_AI_URL") or base
        url = Ai._endpoint(url, capability, selected)
        chosen_model = model if model is not None else (os.environ.get("TINA4_AI_MODEL") or default_model)
        if not isinstance(chosen_model, str) or not chosen_model.strip():
            raise AiConfigError("AI model must be a non-empty string")

        total = float(timeout) if timeout is not None else float(Ai._number("TINA4_AI_TIMEOUT", "60", minimum=0.001))
        if total <= 0:
            raise AiConfigError("AI timeout must be greater than zero")
        connect = float(Ai._number("TINA4_AI_CONNECT_TIMEOUT", "10", minimum=0.001))
        retries = int(Ai._number("TINA4_AI_MAX_RETRIES", "2", minimum=0, integer=True))
        return _Config(selected, url, chosen_model.strip(), key, total, connect, retries)

    @staticmethod
    def _endpoint(value: str, capability: str, provider: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AiConfigError("AI URL must be an http or https URL")
        path = parsed.path.rstrip("/")
        if provider == "anthropic":
            suffix = "/messages"
        elif capability == "embed":
            suffix = "/embeddings"
        else:
            suffix = "/chat/completions"
        if path in {"", "/v1", "/api"}:
            prefix = path or ("/v1" if provider in {"local", "openai"} else "/v1")
            path = prefix + suffix
            parsed = parsed._replace(path=path)
            return parsed.geturl()
        return value

    @staticmethod
    def _headers(config: _Config) -> dict[str, str]:
        headers = {"content-type": "application/json", "accept": "application/json"}
        if config.provider == "openai" and config.key:
            headers["authorization"] = f"Bearer {config.key}"
        elif config.provider == "anthropic" and config.key:
            headers["x-api-key"] = config.key
            headers["anthropic-version"] = "2023-06-01"
        return headers

    @staticmethod
    def _chat_body(
        config: _Config,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": config.model, "messages": messages, "stream": stream}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if config.provider == "anthropic":
            system = [message["content"] for message in messages if message["role"] == "system"]
            body["messages"] = [message for message in messages if message["role"] != "system"]
            body["max_tokens"] = max_tokens if max_tokens is not None else 1024
            if system:
                body["system"] = "\n\n".join(system)
        return body

    @staticmethod
    def _connect(config: _Config, deadline: float, body: dict[str, Any], headers: dict[str, str]) -> _TransportResponse:
        parsed = urlparse(config.url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AiTimeoutError("AI total request timeout expired")
        connect_timeout = min(config.connect_timeout, remaining)
        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        kwargs: dict[str, Any] = {"timeout": connect_timeout}
        if parsed.scheme == "https":
            kwargs["context"] = ssl.create_default_context()
        connection = connection_cls(parsed.hostname, port, **kwargs)
        try:
            try:
                connection.connect()
            except socket.timeout:
                raise AiTimeoutError("AI connection timeout expired") from None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AiTimeoutError("AI total request timeout expired")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            payload = json.dumps(body, separators=(",", ":")).encode()
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("POST", path, body=payload, headers=headers)
            response = connection.getresponse()
            return _TransportResponse(connection, response)
        except socket.timeout:
            connection.close()
            raise AiTimeoutError("AI total request timeout expired") from None
        except AiError:
            connection.close()
            raise
        except (OSError, http.client.HTTPException) as exc:
            connection.close()
            raise AiHTTPError(f"AI transport failed ({type(exc).__name__})") from None

    @staticmethod
    def _retry_delay(response: http.client.HTTPResponse, deadline: float) -> float:
        raw = response.getheader("retry-after")
        try:
            requested = max(0.0, float(raw)) if raw is not None else 0.1
        except ValueError:
            requested = 0.1
        return min(requested, max(0.0, deadline - time.monotonic()))

    @staticmethod
    def _request_json(config: _Config, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + config.total_timeout
        last_error: AiError | None = None
        for attempt in range(config.max_retries + 1):
            transport: _TransportResponse | None = None
            try:
                transport = Ai._connect(config, deadline, body, headers)
                response = transport.response
                status = response.status
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AiTimeoutError("AI total request timeout expired")
                if transport.connection.sock is not None:
                    transport.connection.sock.settimeout(remaining)
                raw_body = response.read()
                if status < 200 or status >= 300:
                    error = AiHTTPError(f"AI provider returned HTTP {status}", status=status)
                    if status == 429 or status >= 500:
                        last_error = error
                        if attempt < config.max_retries:
                            delay = Ai._retry_delay(response, deadline)
                            transport.close()
                            transport = None
                            if delay:
                                time.sleep(delay)
                            continue
                    raise error
                try:
                    parsed = json.loads(raw_body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise AiParseError("AI provider returned malformed JSON") from None
                if not isinstance(parsed, dict):
                    raise AiParseError("AI provider returned a non-object JSON response")
                return parsed
            except (AiTimeoutError, AiHTTPError) as exc:
                last_error = exc
                if isinstance(exc, AiHTTPError) and exc.status is not None:
                    raise
                if attempt >= config.max_retries:
                    raise
            except socket.timeout:
                last_error = AiTimeoutError("AI total request timeout expired")
                if attempt >= config.max_retries:
                    raise last_error from None
            finally:
                if transport is not None:
                    transport.close()
        raise last_error or AiHTTPError("AI request failed")

    @staticmethod
    def _normalize_chat(provider: str, raw: dict[str, Any]) -> ChatResponse:
        try:
            if provider == "anthropic":
                text_parts = [item["text"] for item in raw["content"] if item.get("type", "text") == "text"]
                if not text_parts:
                    raise ValueError
                input_tokens = int(raw.get("usage", {}).get("input_tokens", 0))
                output_tokens = int(raw.get("usage", {}).get("output_tokens", 0))
                usage = {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
                return ChatResponse("".join(text_parts), str(raw.get("model", "")), usage, raw.get("stop_reason"), raw)
            choice = raw["choices"][0]
            text = choice["message"]["content"]
            if not isinstance(text, str):
                raise ValueError
            provider_usage = raw.get("usage", {})
            usage = {
                "prompt_tokens": int(provider_usage.get("prompt_tokens", 0)),
                "completion_tokens": int(provider_usage.get("completion_tokens", 0)),
                "total_tokens": int(provider_usage.get("total_tokens", 0)),
            }
            return ChatResponse(text, str(raw.get("model", "")), usage, choice.get("finish_reason"), raw)
        except (KeyError, IndexError, TypeError, ValueError):
            raise AiParseError("AI provider returned a malformed chat response") from None

    @staticmethod
    def _stream_delta(provider: str, data: str) -> tuple[bool, str | None]:
        if data == "[DONE]":
            return True, None
        try:
            event = json.loads(data)
            if provider == "anthropic":
                delta = event.get("delta", {})
                text = delta.get("text") if event.get("type") == "content_block_delta" else None
            else:
                text = event.get("choices", [{}])[0].get("delta", {}).get("content")
        except (json.JSONDecodeError, IndexError, TypeError, UnicodeDecodeError):
            raise AiParseError("AI provider returned malformed stream data") from None
        if text is not None and not isinstance(text, str):
            raise AiParseError("AI provider returned malformed stream data")
        return False, text

    @staticmethod
    def _stream_data(transport: _TransportResponse, deadline: float) -> Iterator[str]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AiTimeoutError("AI total request timeout expired")
            if transport.connection.sock is not None:
                transport.connection.sock.settimeout(remaining)
            line = transport.response.readline()
            if not line:
                return
            stripped = line.decode("utf-8", errors="strict").strip()
            if stripped.startswith("data:"):
                yield stripped[5:].strip()

    @staticmethod
    def _stream(config: _Config, headers: dict[str, str], body: dict[str, Any]) -> Iterator[str]:
        def iterator() -> Iterator[str]:
            deadline = time.monotonic() + config.total_timeout
            yielded = False
            for attempt in range(config.max_retries + 1):
                transport: _TransportResponse | None = None
                try:
                    stream_headers = {**headers, "accept": "text/event-stream"}
                    transport = Ai._connect(config, deadline, body, stream_headers)
                    response = transport.response
                    if response.status < 200 or response.status >= 300:
                        status = response.status
                        response.read()
                        error = AiHTTPError(f"AI provider returned HTTP {status}", status=status)
                        if (status == 429 or status >= 500) and attempt < config.max_retries:
                            delay = Ai._retry_delay(response, deadline)
                            transport.close()
                            transport = None
                            if delay:
                                time.sleep(delay)
                            continue
                        raise error
                    completed = False
                    for data in Ai._stream_data(transport, deadline):
                        completed, text = Ai._stream_delta(config.provider, data)
                        if completed:
                            break
                        if text is not None:
                            yielded = True
                            yield text
                    if completed:
                        return
                    raise AiParseError("AI provider stream ended before [DONE]")
                except (AiHTTPError, AiTimeoutError):
                    if yielded or attempt >= config.max_retries:
                        raise
                except (socket.timeout, OSError, http.client.HTTPException) as exc:
                    error: AiError = (
                        AiTimeoutError("AI total request timeout expired")
                        if isinstance(exc, socket.timeout)
                        else AiHTTPError(f"AI transport failed ({type(exc).__name__})")
                    )
                    if yielded or attempt >= config.max_retries:
                        raise error from None
                finally:
                    if transport is not None:
                        transport.close()

        return iterator()
