# Tina4 Debug — Rich error overlay for development mode.
"""
Renders a rich HTML error page (exception type + message, the full stack with a
seven-line source window per frame, request details, and the environment) when an
unhandled exception reaches the server dispatch in development.

    from tina4_python.debug.error_overlay import render_error_overlay, is_debug_mode

    try:
        handler(request, response)
    except Exception as exc:
        if is_debug_mode():
            html = render_error_overlay(exc, request)

Dev-only: the caller gates this on ``is_debug_mode()`` (``TINA4_DEBUG``). The
production 500 is NOT rendered here — the server dispatch renders ``errors/500.twig``
with an empty ``error_message`` (CWE-209), so the exception detail stays in the
server log only, never in the response body.

Sensitive request fields (``Authorization`` / ``Cookie`` / ``Set-Cookie`` headers and
password-like body/param keys) are redacted even in the dev overlay, the frame count
is capped, and the caller wraps this render in a guard, so a broken overlay or a
recursive stack still yields a bounded, safe 500.
"""
import os
import re
import sys
import html as html_mod
import traceback
import linecache
from typing import Any


# ── Colour palette (Catppuccin Mocha) ────────────────────────────────────
_BG = "#1e1e2e"
_SURFACE = "#313244"
_OVERLAY = "#45475a"
_TEXT = "#cdd6f4"
_SUBTEXT = "#a6adc8"
_RED = "#f38ba8"
_YELLOW = "#f9e2af"
_BLUE = "#89b4fa"
_GREEN = "#a6e3a1"
_LAVENDER = "#b4befe"
_PEACH = "#fab387"
_ERROR_LINE_BG = "rgba(243,139,168,0.15)"

_CONTEXT_LINES = 7  # lines above/below the error line

# OVERLAY-DEC-03: cap the rendered frames so a deep/recursive stack
# (a RecursionError-class trace of thousands of frames) yields a bounded page
# with one source-file read per SHOWN frame, not an unbounded one.
_MAX_FRAMES = 50

# OVERLAY-DEC-02: request fields whose KEY matches this are masked in the dev
# overlay, so a bearer token, cookie or submitted password is never rendered in
# cleartext even when TINA4_DEBUG is on. Matched case-insensitively on the field
# name (``Authorization``/``Cookie``/``Set-Cookie`` headers via authorization|cookie;
# ``password``/``token``/``secret``/``api_key`` body/param keys via the rest). Over-
# matching (a benign field containing "key") is the SAFE direction in a dev tool:
# over-masking hides nothing that matters, under-masking leaks a secret.
_SENSITIVE_KEY_RE = re.compile(
    r"password|passwd|secret|token|authorization|cookie|key", re.IGNORECASE
)
_REDACTED = "[redacted]"


def _read_source_lines(filename: str, lineno: int, context: int = _CONTEXT_LINES) -> list[tuple[int, str, bool]]:
    """Read source lines around *lineno*.  Returns list of (line_number, text, is_error_line)."""
    lines: list[tuple[int, str, bool]] = []
    start = max(1, lineno - context)
    end = lineno + context
    for i in range(start, end + 1):
        line = linecache.getline(filename, i)
        if not line and i > lineno:
            break
        lines.append((i, line.rstrip("\n"), i == lineno))
    return lines


def _escape(text: str) -> str:
    return html_mod.escape(str(text))


def _redact(key: str, value: str) -> str:
    """Mask a sensitive request value (OVERLAY-DEC-02).

    Returns ``[redacted]`` when *key* names a secret field (an
    ``Authorization``/``Cookie``/``Set-Cookie`` header or a
    ``password``/``token``/``secret``/``key``-like body/param key), otherwise the
    value unchanged. The escape happens AFTER this, so the mask itself is inert.
    """
    return _REDACTED if _SENSITIVE_KEY_RE.search(str(key)) else value


def _format_source_block(filename: str, lineno: int) -> str:
    """Return an HTML block with syntax-highlighted source code."""
    lines = _read_source_lines(filename, lineno)
    if not lines:
        return ""
    rows: list[str] = []
    for num, text, is_error in lines:
        bg = f"background:{_ERROR_LINE_BG};" if is_error else ""
        marker = "&#x25b6;" if is_error else " "
        rows.append(
            f'<div style="{bg}display:flex;padding:1px 0;">'
            f'<span style="color:{_YELLOW};min-width:3.5em;text-align:right;padding-right:1em;user-select:none;">{num}</span>'
            f'<span style="color:{_RED};width:1.2em;user-select:none;">{marker}</span>'
            f'<span style="color:{_TEXT};white-space:pre-wrap;tab-size:4;">{_escape(text)}</span>'
            f"</div>"
        )
    return (
        f'<div style="background:{_SURFACE};border-radius:6px;padding:12px;overflow-x:auto;'
        f'font-family:\'SF Mono\',\'Fira Code\',\'Consolas\',monospace;font-size:13px;line-height:1.6;">'
        + "\n".join(rows)
        + "</div>"
    )


def _format_frame(frame: traceback.FrameSummary, captured_at: float = 0.0) -> str:
    """Render one stack frame.

    When the file was modified AFTER `captured_at`, append a
    "(file modified since)" badge so a stale browser-cached overlay
    can't lie about what the source looks like now. The AI coder
    often rewrites files in place between page loads, leaving the
    overlay's source view showing different code than what raised
    the error.
    """
    source = _format_source_block(frame.filename, frame.lineno) if frame.filename and frame.lineno else ""
    stale_badge = ""
    if captured_at and frame.filename:
        try:
            mtime = os.path.getmtime(frame.filename)
            if mtime > captured_at + 0.5:  # 0.5s margin for fs noise
                from datetime import datetime, timezone
                mtime_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%H:%M:%S")
                stale_badge = (
                    f' <span style="background:{_PEACH};color:{_BG};padding:1px 8px;'
                    f'border-radius:3px;font-size:11px;font-weight:700;margin-left:6px;">'
                    f'FILE MODIFIED @ {mtime_iso} — source may not match what failed</span>'
                )
        except OSError:
            pass
    return (
        f'<div style="margin-bottom:16px;">'
        f'<div style="margin-bottom:4px;">'
        f'<span style="color:{_BLUE};">{_escape(frame.filename)}</span>'
        f'<span style="color:{_SUBTEXT};"> : </span>'
        f'<span style="color:{_YELLOW};">{frame.lineno}</span>'
        f'<span style="color:{_SUBTEXT};"> in </span>'
        f'<span style="color:{_GREEN};">{_escape(frame.name)}</span>'
        f"{stale_badge}"
        f"</div>"
        f"{source}"
        f"</div>"
    )


def _collapsible(title: str, content: str, open_by_default: bool = False) -> str:
    open_attr = " open" if open_by_default else ""
    return (
        f'<details style="margin-top:16px;"{open_attr}>'
        f'<summary style="cursor:pointer;color:{_LAVENDER};font-weight:600;font-size:15px;'
        f'padding:8px 0;user-select:none;">{_escape(title)}</summary>'
        f'<div style="padding:8px 0;">{content}</div>'
        f"</details>"
    )


def _table(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return '<span style="color:{_SUBTEXT};">None</span>'
    rows = ""
    for key, val in pairs:
        rows += (
            f"<tr>"
            f'<td style="color:{_PEACH};padding:4px 16px 4px 0;vertical-align:top;white-space:nowrap;">{_escape(key)}</td>'
            f'<td style="color:{_TEXT};padding:4px 0;word-break:break-all;">{_escape(val)}</td>'
            f"</tr>"
        )
    return f'<table style="border-collapse:collapse;width:100%;">{rows}</table>'


def render_error_overlay(exception: BaseException, request: Any = None) -> str:
    """Render a rich HTML error overlay.

    Args:
        exception: The caught exception.
        request: Optional request-like object or dict with method, url, headers, etc.

    Returns:
        A complete HTML page string.
    """
    import time as _time
    captured_at = _time.time()
    captured_iso = _time.strftime("%H:%M:%S UTC", _time.gmtime(captured_at))

    exc_type = type(exception).__qualname__
    exc_msg = str(exception)
    tb = traceback.extract_tb(exception.__traceback__)

    # ── Stack trace ──
    # Each frame compares its source file's mtime to captured_at and
    # flags itself if the file has been modified since — protects
    # against the "browser cached an old overlay, then the AI rewrote
    # the file" confusion where displayed source no longer matches
    # what actually raised the error.
    # OVERLAY-DEC-03: cap the rendered frames. A recursive stack of thousands of
    # frames would otherwise do one source-file read per frame and emit an
    # unbounded page; render only the innermost _MAX_FRAMES and note the rest.
    ordered = list(reversed(tb))
    frames_html = ""
    for frame in ordered[:_MAX_FRAMES]:
        frames_html += _format_frame(frame, captured_at=captured_at)
    hidden = len(ordered) - _MAX_FRAMES
    if hidden > 0:
        frames_html += (
            f'<div style="color:{_SUBTEXT};padding:8px 0;font-size:13px;">'
            f'&#8230; {hidden} more stack frames hidden (truncated at {_MAX_FRAMES})'
            f"</div>"
        )

    # ── Request info ──
    request_pairs: list[tuple[str, str]] = []
    if request is not None:
        if isinstance(request, dict):
            req = request
        else:
            req = {}
            for attr in ("method", "url", "path", "ip", "content_type", "headers", "params", "query", "body"):
                val = getattr(request, attr, None)
                req[attr] = val
        for k, v in req.items():
            if v is None:
                request_pairs.append((str(k), "(none)"))
            elif isinstance(v, dict):
                if v:
                    for hk, hv in v.items():
                        pair_key = f"{k}.{hk}"
                        request_pairs.append((pair_key, _redact(pair_key, str(hv))))
                else:
                    request_pairs.append((str(k), "(empty)"))
            else:
                request_pairs.append((str(k), _redact(str(k), str(v))))

    request_section = _collapsible("Request Details", _table(request_pairs)) if request_pairs else ""

    # ── Environment ──
    env_pairs = [
        ("Framework", "Tina4 Python"),
        ("Version", _get_version()),
        ("Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
        ("Platform", sys.platform),
        ("Debug", os.environ.get("TINA4_DEBUG", "false")),
        ("Log Level", os.environ.get("TINA4_LOG_LEVEL", "ERROR")),
    ]
    env_section = _collapsible("Environment", _table(env_pairs))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tina4 Error — {_escape(exc_type)}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:{_BG};color:{_TEXT};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:24px;line-height:1.5;}}
</style>
</head>
<body>
<div style="max-width:960px;margin:0 auto;">
  <div style="margin-bottom:24px;">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
      <span style="background:{_RED};color:{_BG};padding:4px 12px;border-radius:4px;font-weight:700;font-size:13px;text-transform:uppercase;">Error</span>
      <span style="color:{_SUBTEXT};font-size:14px;">Tina4 Debug Overlay</span>
      <span style="color:{_SUBTEXT};font-size:12px;margin-left:auto;font-family:'SF Mono',Menlo,monospace;">captured {captured_iso}</span>
    </div>
    <h1 style="color:{_RED};font-size:28px;font-weight:700;margin-bottom:8px;">{_escape(exc_type)}</h1>
    <p style="color:{_TEXT};font-size:18px;font-family:'SF Mono','Fira Code','Consolas',monospace;background:{_SURFACE};padding:12px 16px;border-radius:6px;border-left:4px solid {_RED};">{_escape(exc_msg)}</p>
  </div>
  {_collapsible("Stack Trace", frames_html, open_by_default=True)}
  {request_section}
  {env_section}
  <div style="margin-top:32px;padding-top:16px;border-top:1px solid {_OVERLAY};color:{_SUBTEXT};font-size:12px;">
    Tina4 Debug Overlay &mdash; This page is only shown in debug mode. Set TINA4_DEBUG=false in production.
  </div>
</div>
</body>
</html>"""


def is_debug_mode() -> bool:
    """Return True if TINA4_DEBUG is enabled."""
    from tina4_python.dotenv import is_truthy
    return is_truthy(os.environ.get("TINA4_DEBUG", ""))


def _get_version() -> str:
    try:
        from tina4_python import __version__
        return __version__
    except Exception:
        return "unknown"
