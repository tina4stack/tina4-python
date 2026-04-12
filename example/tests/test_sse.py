"""Test SSE (Server-Sent Events) formatting — demonstrates: event-stream format,
async generator yielding SSE data lines.

Lightweight tests that verify the SSE data protocol without starting a server.
"""
import asyncio
import json
import queue
import pytest


class TestSSEFormat:
    def test_sse_data_line_format(self):
        """SSE protocol requires 'data: <payload>\\n\\n' format."""
        event = {"type": "sale", "amount": 42.50}
        line = f"data: {json.dumps(event)}\n\n"
        assert line.startswith("data: ")
        assert line.endswith("\n\n")

        parsed = json.loads(line.replace("data: ", "").strip())
        assert parsed["type"] == "sale"
        assert parsed["amount"] == 42.50

    def test_sse_multiple_events(self):
        """Multiple SSE events are separated by double newlines."""
        events = [
            {"type": "sale", "product": "Widget"},
            {"type": "sale", "product": "Gadget"},
        ]
        lines = [f"data: {json.dumps(e)}\n\n" for e in events]
        stream = "".join(lines)

        parts = [p for p in stream.split("\n\n") if p.strip()]
        assert len(parts) == 2

    def test_sse_json_payload_round_trip(self):
        """Verify JSON payloads survive the SSE format encoding."""
        original = {"order_id": 123, "status": "shipped", "items": ["A", "B"]}
        sse_line = f"data: {json.dumps(original)}\n\n"
        decoded = json.loads(sse_line[len("data: "):].strip())
        assert decoded == original


class TestSSEAsyncGenerator:
    @pytest.mark.asyncio
    async def test_generator_yields_from_queue(self):
        """Simulate the store's sales_event_generator pattern."""
        thread_queue = queue.Queue()
        thread_queue.put({"type": "sale", "amount": 10.0})
        thread_queue.put({"type": "sale", "amount": 20.0})

        async def event_generator():
            while True:
                try:
                    event = thread_queue.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    break

        collected = []
        async for line in event_generator():
            collected.append(line)

        assert len(collected) == 2
        first = json.loads(collected[0].replace("data: ", "").strip())
        assert first["amount"] == 10.0

    @pytest.mark.asyncio
    async def test_generator_empty_queue_stops(self):
        """Generator exits cleanly when queue is empty."""
        thread_queue = queue.Queue()

        async def event_generator():
            while True:
                try:
                    event = thread_queue.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    break

        collected = []
        async for line in event_generator():
            collected.append(line)

        assert len(collected) == 0
