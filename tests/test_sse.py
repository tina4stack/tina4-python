# Tests for Response.stream() — Server-Sent Events (SSE) support.
import pytest
from tina4_python.core.response import Response


class TestStreamSSE:
    """Test response.stream() for Server-Sent Events."""

    def test_stream_sets_streaming_flag(self):
        r = Response()

        def generate():
            yield "data: hello\n\n"

        r.stream(generate())
        assert r._is_streaming is True

    def test_stream_stores_source(self):
        r = Response()

        def generate():
            yield "data: hello\n\n"

        gen = generate()
        r.stream(gen)
        assert r._stream_source is gen

    def test_stream_sets_event_stream_content_type(self):
        r = Response()

        def generate():
            yield "data: hello\n\n"

        r.stream(generate())
        assert r.content_type == "text/event-stream"

    def test_stream_sets_cache_control_no_cache(self):
        r = Response()

        def generate():
            yield "data: hello\n\n"

        r.stream(generate())
        assert ("Cache-Control", "no-cache") in r._headers

    def test_stream_sets_connection_keep_alive(self):
        r = Response()

        def generate():
            yield "data: hello\n\n"

        r.stream(generate())
        assert ("Connection", "keep-alive") in r._headers

    def test_stream_sets_x_accel_buffering_no(self):
        r = Response()

        def generate():
            yield "data: hello\n\n"

        r.stream(generate())
        assert ("X-Accel-Buffering", "no") in r._headers

    def test_stream_custom_content_type(self):
        r = Response()

        def generate():
            yield b"\x00\x01\x02"

        r.stream(generate(), "application/octet-stream")
        assert r.content_type == "application/octet-stream"

    def test_stream_custom_content_type_no_sse_headers(self):
        r = Response()

        def generate():
            yield b"\x00\x01\x02"

        r.stream(generate(), "application/octet-stream")
        # Non-SSE content type should NOT add Cache-Control, Connection headers
        assert ("Cache-Control", "no-cache") not in r._headers
        assert ("Connection", "keep-alive") not in r._headers

    def test_stream_returns_self(self):
        r = Response()

        def generate():
            yield "data: hello\n\n"

        result = r.stream(generate())
        assert result is r

    def test_stream_multiple_chunks_from_generator(self):
        r = Response()

        def generate():
            for i in range(3):
                yield f"data: message {i}\n\n"

        gen = generate()
        r.stream(gen)
        # Verify the generator can be consumed
        chunks = list(r._stream_source)
        assert len(chunks) == 3
        assert chunks[0] == "data: message 0\n\n"
        assert chunks[1] == "data: message 1\n\n"
        assert chunks[2] == "data: message 2\n\n"

    def test_stream_default_status_code(self):
        r = Response()

        def generate():
            yield "data: hello\n\n"

        r.stream(generate())
        assert r.status_code == 200

    def test_stream_preserves_existing_headers(self):
        r = Response()
        r.header("X-Custom", "value")

        def generate():
            yield "data: hello\n\n"

        r.stream(generate())
        assert ("X-Custom", "value") in r._headers
        assert ("Cache-Control", "no-cache") in r._headers

    def test_stream_preserves_existing_cookies(self):
        r = Response()
        r.cookie("session", "abc123")

        def generate():
            yield "data: hello\n\n"

        r.stream(generate())
        assert len(r._cookies) == 1
        assert "session=abc123" in r._cookies[0]
