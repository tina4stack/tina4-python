# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Dev-admin memory figures, measured in a real process. No test doubles.
"""
/__dev/api/status ``memory_usage_mb`` and /__dev/api/system ``memory_mb`` are
the CURRENT resident set size; ``peak_memory_mb`` is the high-water mark.

Each endpoint test starts a fresh Python process. That process grows by a real,
touched buffer, frees it, then asks the real front controller
(``tina4_python.core.server.app``, the ASGI entry point uvicorn calls) for both
endpoints, and reads the kernel's own counters for itself. Nothing is replaced:
the "without psutil" case runs the interpreter with ``-S``, so psutil is truly
not importable, and the probe checks that before it measures.

Platforms that cannot provide a measurement skip with a ``[needs:...]`` tag
(see tests/conftest.py) rather than faking one.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BUFFER_MB = 150
# How far below the high-water mark a current figure must sit after the buffer
# is freed. Well under BUFFER_MB, so allocator slack cannot make it flaky.
CLEAR_OF_PEAK_MB = BUFFER_MB * 0.6

HAS_PROCFS = os.path.exists("/proc/self/status")
HAS_PSUTIL = importlib.util.find_spec("psutil") is not None

_PROBE = r'''
import asyncio, gc, importlib.util, json, sys


def kernel_mb(field):
    """A /proc/self/status field (kB) in MB, or None where there is no procfs."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith(field + ":"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


def get(path):
    """One real GET through the real ASGI front controller."""
    from tina4_python.core.server import app
    status, body = [], bytearray()
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "headers": [],
        "client": ("127.0.0.1", 50000), "server": ("localhost", 7145), "root_path": "",
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status.append(message["status"])
        elif message["type"] == "http.response.body":
            body.extend(message.get("body") or b"")

    asyncio.run(app(scope, receive, send))
    if status != [200]:
        raise SystemExit(f"GET {path} answered {status}: {bytes(body[:500])!r}")
    return json.loads(body)


get("/__dev/api/status")  # first request: imports and route table, before the buffer

buffer = bytearray(int(sys.argv[1]) * 1024 * 1024)
for offset in range(0, len(buffer), 4096):  # touch every page so it is resident
    buffer[offset] = 1
rss_while_held_mb = kernel_mb("VmRSS")
del buffer
gc.collect()

status = get("/__dev/api/status")
system = get("/__dev/api/system")
print("PROBE " + json.dumps({
    "psutil_importable": importlib.util.find_spec("psutil") is not None,
    "memory_usage_mb": status["memory_usage_mb"],
    "peak_memory_mb": status["peak_memory_mb"],
    "system_memory_mb": system["memory_mb"],
    "vm_rss_mb": kernel_mb("VmRSS"),
    "vm_hwm_mb": kernel_mb("VmHWM"),
    "rss_while_held_mb": rss_while_held_mb,
}))
'''


def _measure(tmp_path, *interpreter_flags):
    """Run the probe in a fresh interpreter and return what it measured."""
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(REPO_ROOT), "TINA4_DEBUG": "true", "TINA4_NO_BROWSER": "true"})
    completed = subprocess.run(
        [sys.executable, *interpreter_flags, "-c", _PROBE, str(BUFFER_MB)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-4000:]
    line = next(line for line in reversed(completed.stdout.splitlines()) if line.startswith("PROBE "))
    return json.loads(line[len("PROBE "):])


def _assert_current_not_peak(figures):
    real_mb = figures["vm_rss_mb"]
    high_water_mb = figures["vm_hwm_mb"]
    # The scenario really happened: the buffer was resident, then given back.
    assert figures["rss_while_held_mb"] - real_mb > CLEAR_OF_PEAK_MB, figures
    assert high_water_mb - real_mb > CLEAR_OF_PEAK_MB, figures
    for name in ("memory_usage_mb", "system_memory_mb"):
        value = figures[name]
        # Positive: the kernel's current RSS, read independently.
        assert value is not None and abs(value - real_mb) <= 15 + 0.1 * real_mb, (
            f"{name}={value} MB, but the kernel reports a current RSS of {real_mb:.1f} MB "
            f"(peak {high_water_mb:.1f} MB): {figures}"
        )
        # Negative: not the high-water mark, by the endpoint's own peak or the kernel's.
        assert figures["peak_memory_mb"] - value > CLEAR_OF_PEAK_MB, f"{name} is the peak: {figures}"
        assert high_water_mb - value > CLEAR_OF_PEAK_MB, f"{name} is the peak: {figures}"


@pytest.mark.skipif(not HAS_PROCFS, reason="[needs:os=linux] reads the kernel's VmRSS/VmHWM "
                    "from /proc/self/status")
def test_without_psutil_memory_is_the_current_rss_not_the_peak(tmp_path):
    """No psutil: both current-memory figures come from VmRSS, not ru_maxrss."""
    figures = _measure(tmp_path, "-S")
    assert figures["psutil_importable"] is False, "-S should leave psutil unimportable"
    _assert_current_not_peak(figures)
    # peak_memory_mb is still the real high-water mark, in MB (VmHWM, read independently).
    high_water_mb = figures["vm_hwm_mb"]
    assert abs(figures["peak_memory_mb"] - high_water_mb) <= 2 + 0.02 * high_water_mb, figures


@pytest.mark.skipif(not (HAS_PROCFS and HAS_PSUTIL),
                    reason="[needs:runtime=psutil] [needs:os=linux] psutil must be installed, "
                    "and /proc/self/status gives the independent current RSS")
def test_with_psutil_memory_is_the_current_rss_not_the_peak(tmp_path):
    """psutil installed: both current-memory figures are its RSS, which the
    kernel's VmRSS confirms, and neither is the peak."""
    figures = _measure(tmp_path)
    assert figures["psutil_importable"] is True
    _assert_current_not_peak(figures)


@pytest.mark.skipif(HAS_PROCFS, reason="[needs:os=non-linux] needs a platform with no "
                    "/proc/self/status, where current RSS has no zero-dependency source")
def test_where_current_memory_cannot_be_read_it_is_unknown_not_the_peak(tmp_path):
    """No /proc and no psutil (Windows, macOS): status reports the stable 0.0
    and system reports None (the dashboard shows "?"). The peak, where the
    platform has one, is never passed off as current usage."""
    figures = _measure(tmp_path, "-S")
    assert figures["psutil_importable"] is False, "-S should leave psutil unimportable"
    assert figures["memory_usage_mb"] == 0.0, figures
    assert figures["system_memory_mb"] is None, figures
    if sys.platform != "win32":  # POSIX: ru_maxrss knows the peak, and it is not current usage
        assert figures["peak_memory_mb"] >= BUFFER_MB, figures


@pytest.mark.skipif(sys.platform == "win32",
                    reason="[needs:os=posix] ru_maxrss comes from the resource module, "
                    "which Windows does not have")
def test_peak_rss_is_megabytes_on_this_platform():
    """_peak_rss_mb() converts ru_maxrss to MB with this kernel's unit (bytes on
    Apple's kernel, kilobytes elsewhere). Hold a real touched buffer: the peak
    must be at least that buffer and at most the machine's physical memory. The
    wrong unit misses by a factor of 1024 either way. On Linux it must also
    match the kernel's own high-water mark, VmHWM."""
    from tina4_python.dev_admin import _peak_rss_mb

    buffer = bytearray(BUFFER_MB * 1024 * 1024)
    for offset in range(0, len(buffer), 4096):
        buffer[offset] = 1
    peak_mb = _peak_rss_mb()
    high_water_mb = None
    if HAS_PROCFS:
        with open("/proc/self/status") as fh:
            high_water_mb = next(int(line.split()[1]) for line in fh if line.startswith("VmHWM:")) / 1024
    del buffer

    physical_mb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 * 1024)
    assert BUFFER_MB <= peak_mb <= physical_mb, (
        f"peak {peak_mb} MB while holding a {BUFFER_MB} MB buffer on a {physical_mb:.0f} MB machine"
    )
    if high_water_mb is not None:
        assert abs(peak_mb - high_water_mb) <= 2 + 0.02 * high_water_mb, (
            f"peak {peak_mb} MB, but the kernel reports VmHWM {high_water_mb:.1f} MB"
        )
