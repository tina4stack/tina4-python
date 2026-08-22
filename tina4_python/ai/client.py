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
class AiEvent:
    """One typed event yielded by ``Ai.chat(stream=True)`` (ADR-0060).

    The ``type`` discriminant is one of ``text_delta`` / ``tool_call`` /
    ``done`` / ``error``. Only the fields relevant to that type are set;
    everything else stays ``None``. ``done`` fires exactly once after
    every ``text_delta`` and ``tool_call``; ``error`` fires in place of
    ``done`` when the stream fails after the first event.
    """

    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    args: dict | None = None
    finish_reason: str | None = None
    usage: dict | None = None
    message: str | None = None
    code: str | None = None


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
    ) -> "ChatResponse | Iterator[AiEvent]":
        """Send a chat completion request.

        ``stream=True`` returns an iterator of ``AiEvent`` records
        (``text_delta`` / ``tool_call`` / ``done`` / ``error``) per
        ADR-0060; ``stream=False`` returns a single ``ChatResponse``.
        """
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
            Ai._validate_content(message.get("content"))

    @staticmethod
    def _validate_content(content: Any) -> None:
        """Accept a plain string OR a non-empty list of content parts.

        Parts (ADR-0060 multimodal):
        - ``{"type": "text",  "text":   <str>}``
        - ``{"type": "image", "source": <str>}``  where ``source`` is a
          ``data:<media_type>;base64,<payload>`` URI or an http(s) URL.

        Anything else raises ``AiConfigError`` before the request goes
        out. Both the OpenAI and Anthropic provider builders trust the
        shape after validation.
        """
        if isinstance(content, str):
            return
        if not isinstance(content, list) or not content:
            raise AiConfigError(
                "Each AI message content must be a string or non-empty list of parts")
        for part in content:
            if not isinstance(part, dict):
                raise AiConfigError("Content parts must be objects")
            kind = part.get("type")
            if kind == "text":
                if not isinstance(part.get("text"), str):
                    raise AiConfigError("text part must have a string 'text' field")
            elif kind == "image":
                source = part.get("source")
                if not isinstance(source, str) or not source:
                    raise AiConfigError("image part must have a string 'source' field")
                if not (source.startswith("data:")
                        or source.startswith("https://")
                        or source.startswith("http://")):
                    raise AiConfigError(
                        "image part 'source' must be a data: URI or http(s) URL")
            else:
                raise AiConfigError("Content part 'type' must be text or image")

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
        translated = [Ai._translate_message(config.provider, message)
                      for message in messages]
        body: dict[str, Any] = {"model": config.model, "messages": translated, "stream": stream}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if config.provider == "anthropic":
            # System messages are hoisted to the top-level `system` field on
            # Anthropic; only string system content is supported (multimodal
            # in a system prompt is not a real provider capability today).
            system_texts: list[str] = []
            non_system: list[dict[str, Any]] = []
            for message in translated:
                if message["role"] == "system":
                    content = message["content"]
                    if isinstance(content, str):
                        system_texts.append(content)
                    else:
                        # Extract text parts only; drop images from system prompt.
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                system_texts.append(part.get("text", ""))
                else:
                    non_system.append(message)
            body["messages"] = non_system
            body["max_tokens"] = max_tokens if max_tokens is not None else 1024
            if system_texts:
                body["system"] = "\n\n".join(system_texts)
        return body

    @staticmethod
    def _translate_message(provider: str, message: dict[str, Any]) -> dict[str, Any]:
        """Translate a Tina4-shape message to the provider-native shape.

        String content passes through unchanged in every provider. A
        list-of-parts message translates image parts to each provider's
        native shape and leaves text parts alone.
        """
        content = message.get("content")
        if isinstance(content, str):
            return dict(message)
        translated: list[dict[str, Any]] = []
        for part in content or []:
            kind = part.get("type")
            if kind == "text":
                translated.append({"type": "text", "text": part.get("text", "")})
                continue
            # kind == "image" — validated already
            source = part["source"]
            if provider == "anthropic":
                translated.append(Ai._anthropic_image_part(source))
            else:
                # openai + local (llama.cpp, ollama openai-shim, etc.) share
                # OpenAI's image_url shape.
                translated.append({
                    "type": "image_url",
                    "image_url": {"url": source},
                })
        new_message = dict(message)
        new_message["content"] = translated
        return new_message

    @staticmethod
    def _anthropic_image_part(source: str) -> dict[str, Any]:
        """Translate an image source (data:/http(s)) to Anthropic's shape."""
        if source.startswith("data:"):
            # data:image/png;base64,<payload>
            try:
                header, _, payload = source[len("data:"):].partition(",")
                media_type, _, encoding = header.partition(";")
                if encoding != "base64" or not media_type or not payload:
                    raise ValueError
            except ValueError:
                raise AiConfigError(
                    "image data URI must be data:<media_type>;base64,<payload>") from None
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": payload,
                },
            }
        # http(s):// URL — Anthropic accepts image via URL source.
        return {"type": "image", "source": {"type": "url", "url": source}}

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
    def _stream(config: _Config, headers: dict[str, str], body: dict[str, Any]) -> Iterator["AiEvent"]:
        """Yield typed ``AiEvent`` records for a streaming chat call (ADR-0060).

        Delegates SSE framing to ``Api.stream_sse`` — one framer per
        language, no duplicate wire parser in the AI module — and
        translates each ``SseEvent`` into zero or more ``AiEvent``
        records using ``_StreamAggregator``. Retries are attempted only
        before the first event; a mid-stream failure emits one
        ``AiEvent(type='error', ...)`` in place of ``done`` and the
        iterator ends.
        """
        # Local import so the api submodule is loaded lazily (matches the
        # rest of tina4_python's lazy-load posture).
        from tina4_python.api import Api, ApiStreamError, ApiTimeoutError

        stream_headers = {**headers, "accept": "text/event-stream"}
        # A private Api instance keeps SSL / cookies / redirect handling
        # in one place. The Ai timeouts win — Api's env defaults do not
        # apply here because we pass them explicitly.
        transport_api = Api()

        def iterator() -> Iterator[AiEvent]:
            yielded = False
            for attempt in range(config.max_retries + 1):
                aggregator = _StreamAggregator(config.provider)
                sse_iter = None
                try:
                    sse_iter = transport_api.stream_sse(
                        config.url,
                        method="POST",
                        body=body,
                        content_type="application/json",
                        extra_headers=stream_headers,
                        timeout=config.total_timeout,
                        connect_timeout=config.connect_timeout,
                    )
                    stream_ended_cleanly = False
                    for sse_event in sse_iter:
                        if sse_event.data == "[DONE]":
                            for ai_event in aggregator.finalize():
                                yielded = True
                                yield ai_event
                            stream_ended_cleanly = True
                            return
                        for ai_event in aggregator.feed(sse_event):
                            yielded = True
                            yield ai_event
                    if not stream_ended_cleanly:
                        # Provider ended the stream without a [DONE]
                        # sentinel — that is normal for Anthropic
                        # (message_stop is the finalizer) and equivalent
                        # to a clean end for any provider whose sagas we
                        # exhaust. Emit done from whatever state we have.
                        for ai_event in aggregator.finalize():
                            yielded = True
                            yield ai_event
                        return
                except ApiStreamError as exc:
                    status = exc.status
                    if yielded:
                        yield AiEvent(
                            type="error",
                            message="AI stream dropped",
                            code=f"http_{status}" if status else "transport",
                        )
                        return
                    # Pre-first-event failure: retry only on 429/5xx.
                    if (status is not None and (status == 429 or status >= 500)
                            and attempt < config.max_retries):
                        continue
                    if status is not None:
                        raise AiHTTPError(
                            f"AI provider returned HTTP {status}",
                            status=status) from None
                    # No status = connect/drop error. Retry within budget.
                    if attempt < config.max_retries:
                        continue
                    raise AiHTTPError("AI transport failed") from None
                except ApiTimeoutError:
                    if yielded:
                        yield AiEvent(
                            type="error",
                            message="AI stream timed out",
                            code="timeout",
                        )
                        return
                    if attempt < config.max_retries:
                        continue
                    raise AiTimeoutError(
                        "AI total request timeout expired") from None
                except AiParseError as exc:
                    # Malformed tool-call args or invalid stream data —
                    # per ADR-0060, tool-call JSON parse failures raise
                    # ``AiParseError`` (not an error event). We terminate
                    # by re-raising so the caller sees the exception.
                    if yielded:
                        # But if we already yielded, surface it as an
                        # error event so the iterator finishes cleanly.
                        yield AiEvent(
                            type="error",
                            message=str(exc),
                            code="parse",
                        )
                        return
                    raise
                finally:
                    if sse_iter is not None:
                        close = getattr(sse_iter, "close", None)
                        if callable(close):
                            close()
        return iterator()


class _StreamAggregator:
    """Turn provider SSE frames into typed ``AiEvent`` records (ADR-0060).

    OpenAI streams tool-call arguments as text fragments spread across
    many chunks; Anthropic wraps them in ``content_block_*`` events. We
    buffer the fragments per tool-call index and emit ONE ``tool_call``
    event when the fragments together form parseable JSON. Text deltas
    pass through as they arrive.
    """

    def __init__(self, provider: str):
        self.provider = provider
        # Keyed by tool_call index (OpenAI) or block index (Anthropic).
        self._tool_calls: dict[int, dict[str, Any]] = {}
        self._emitted: set[int] = set()
        self._finish_reason: str | None = None
        self._usage: dict[str, Any] | None = None

    def feed(self, sse_event: Any) -> list["AiEvent"]:
        raw = sse_event.data
        if not raw:
            return []
        try:
            event = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Malformed frame — a provider that emits garbage between
            # data lines should not stop the stream; but we can't act
            # on it either. Ignore.
            return []
        if self.provider == "anthropic":
            return self._feed_anthropic(event)
        return self._feed_openai_style(event)

    def finalize(self) -> list["AiEvent"]:
        out = list(self._flush_pending_tool_calls())
        out.append(AiEvent(
            type="done",
            finish_reason=self._finish_reason or "stop",
            usage=self._usage,
        ))
        return out

    def _feed_openai_style(self, event: dict[str, Any]) -> list["AiEvent"]:
        out: list[AiEvent] = []
        # Some providers emit a lone usage frame at the end.
        if event.get("usage"):
            self._usage = event["usage"]
        choices = event.get("choices") or []
        if not choices:
            return out
        choice = choices[0]
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str) and content:
            out.append(AiEvent(type="text_delta", text=content))
        for fragment in delta.get("tool_calls") or []:
            if not isinstance(fragment, dict):
                continue
            idx = fragment.get("index", 0)
            slot = self._tool_calls.setdefault(
                idx, {"id": None, "name": None, "args_buf": ""})
            if fragment.get("id"):
                slot["id"] = fragment["id"]
            fn = fragment.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            args_frag = fn.get("arguments")
            if isinstance(args_frag, str):
                slot["args_buf"] += args_frag
        finish = choice.get("finish_reason")
        if finish:
            self._finish_reason = finish
            out.extend(self._flush_pending_tool_calls())
        return out

    def _feed_anthropic(self, event: dict[str, Any]) -> list["AiEvent"]:
        out: list[AiEvent] = []
        etype = event.get("type")
        if etype == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                idx = event.get("index", 0)
                self._tool_calls[idx] = {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "args_buf": "",
                }
        elif etype == "content_block_delta":
            delta = event.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                text = delta.get("text")
                if isinstance(text, str) and text:
                    out.append(AiEvent(type="text_delta", text=text))
            elif dtype == "input_json_delta":
                idx = event.get("index", 0)
                slot = self._tool_calls.get(idx)
                if slot is not None:
                    frag = delta.get("partial_json")
                    if isinstance(frag, str):
                        slot["args_buf"] += frag
        elif etype == "content_block_stop":
            idx = event.get("index", 0)
            if idx in self._tool_calls and idx not in self._emitted:
                out.extend(self._emit_tool_call(idx))
        elif etype == "message_delta":
            delta = event.get("delta") or {}
            if delta.get("stop_reason"):
                self._finish_reason = delta["stop_reason"]
            if event.get("usage"):
                self._usage = event["usage"]
        elif etype == "message_stop":
            # done is emitted by finalize() at end of stream.
            pass
        return out

    def _emit_tool_call(self, idx: int) -> list["AiEvent"]:
        slot = self._tool_calls[idx]
        if idx in self._emitted:
            return []
        buf = slot.get("args_buf") or ""
        try:
            args = json.loads(buf) if buf else {}
        except (json.JSONDecodeError, ValueError):
            raise AiParseError(
                f"AI tool_call arguments failed to parse for '"
                f"{slot.get('name') or 'tool'}'") from None
        if not isinstance(args, dict):
            raise AiParseError("AI tool_call arguments must decode to an object")
        self._emitted.add(idx)
        return [AiEvent(
            type="tool_call",
            id=slot.get("id") or "",
            name=slot.get("name") or "",
            args=args,
        )]

    def _flush_pending_tool_calls(self) -> list["AiEvent"]:
        out: list[AiEvent] = []
        for idx in sorted(self._tool_calls):
            if idx not in self._emitted:
                out.extend(self._emit_tool_call(idx))
        return out
