# Tina4 Debug — Rich error overlay for development mode.
"""
Renders a professional, syntax-highlighted HTML error page when an unhandled
exception occurs in a route handler.

    from tina4_python.debug.error_overlay import render_error_overlay

    try:
        handler(request, response)
    except Exception as exc:
        html = render_error_overlay(exc, request_info={"method": "GET", "url": "/api/users"})

Only activate when TINA4_DEBUG is true.  In production, call
render_production_error() instead for a safe, generic error page.
"""
import os
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


def _format_frame(frame: traceback.FrameSummary) -> str:
    """Render one stack frame."""
    source = _format_source_block(frame.filename, frame.lineno) if frame.filename and frame.lineno else ""
    return (
        f'<div style="margin-bottom:16px;">'
        f'<div style="margin-bottom:4px;">'
        f'<span style="color:{_BLUE};">{_escape(frame.filename)}</span>'
        f'<span style="color:{_SUBTEXT};"> : </span>'
        f'<span style="color:{_YELLOW};">{frame.lineno}</span>'
        f'<span style="color:{_SUBTEXT};"> in </span>'
        f'<span style="color:{_GREEN};">{_escape(frame.name)}</span>'
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
    exc_type = type(exception).__qualname__
    exc_msg = str(exception)
    tb = traceback.extract_tb(exception.__traceback__)

    # ── Stack trace ──
    frames_html = ""
    for frame in reversed(tb):
        frames_html += _format_frame(frame)

    # ── Request info ──
    request_pairs: list[tuple[str, str]] = []
    if request is not None:
        if isinstance(request, dict):
            req = request
        else:
            req = {}
            for attr in ("method", "url", "path", "headers", "params", "query", "body"):
                val = getattr(request, attr, None)
                if val is not None:
                    req[attr] = val
        for k, v in req.items():
            if isinstance(v, dict):
                for hk, hv in v.items():
                    request_pairs.append((f"{k}.{hk}", str(hv)))
            else:
                request_pairs.append((str(k), str(v)))

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


def render_production_error(status_code: int = 500, message: str = "Internal Server Error") -> str:
    """Render a safe, generic error page for production use."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{status_code} — {_escape(message)}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:{_BG};color:{_TEXT};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
display:flex;justify-content:center;align-items:center;min-height:100vh;text-align:center;}}
</style>
</head>
<body>
<div>
  <h1 style="font-size:72px;color:{_RED};margin-bottom:16px;">{status_code}</h1>
  <p style="font-size:20px;color:{_SUBTEXT};">{_escape(message)}</p>
  <p style="margin-top:24px;font-size:14px;color:{_OVERLAY};">Tina4 Python</p>
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
