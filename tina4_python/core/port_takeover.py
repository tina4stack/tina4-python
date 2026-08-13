"""Identity-checked port takeover, shared by the CLI and the runtime paths.

`tina4 serve` reclaims a busy port so the edit-restart loop does not fail with
"address already in use". The convenience has a sharp edge: "whatever is
listening" is not always the old Tina4 server, and before this module BOTH
takeover paths (the CLI `killProcessOnPort` and the runtime bind-failure
`_kill_port`) SIGTERM'd whatever held the port, with NO check that the victim was
a Tina4 dev server. A foreign holder -- another developer's server, a database, a
stray `http.server` -- was killed.

This module is the ONE takeover implementation both paths call (TAKEOVER-DEC-02),
so the runtime path can never again be a weaker twin of the CLI path. It adds:

- **Identity (TAKEOVER-DEC-01).** A Tina4 dev server writes a per-port PID file
  (`data/.tina4-serve-<port>.pid`) when it binds and removes it on clean exit.
  Takeover only signals a holder whose PID matches that file. A holder with no
  matching Tina4 PID file is REFUSED, never killed.
- **Dev gate + opt-out (TAKEOVER-DEC-03).** Takeover runs only in dev
  (`TINA4_DEBUG` truthy) and only when not opted out (`TINA4_NO_TAKEOVER` /
  `tina4 serve --no-kill`). A production bind never kills a port holder.
- **The existing PID safety filter and container guard** (`selectable_pids`,
  `in_container`) still apply on top, unchanged.

Refusing is always safe: the worst case is the developer frees the port by hand.
Over-killing was the bug this fixes.

tina4: identity is a PID+port match against a file Tina4 wrote. The only false
match is PID reuse -- the old server crashed WITHOUT cleaning up its file, the OS
recycled its PID, and the recycled process grabbed the SAME port before the next
serve. That window is tiny (takeover only fires on a held port; a clean exit
removes the file; a fresh bind overwrites it) and the failure mode is a refusal,
never a wrong kill. A `/__dev` HTTP probe was the alternative but it cannot
reclaim a hung server that still holds the port yet no longer answers -- the exact
papercut takeover exists for -- so the PID file is the more robust signal.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field


# ── takeover result ───────────────────────────────────────────────────────

# Nothing was on the port (or only unsafe PIDs) -- bind may proceed.
NOTHING = "nothing"
# A confirmed Tina4 dev server was signalled -- the port is being reclaimed.
KILLED = "killed"
# The holder is NOT identifiably Tina4 -- refused, nothing killed.
REFUSED_FOREIGN = "refused_foreign"
# Takeover is opted out (TINA4_NO_TAKEOVER / --no-kill) -- refused.
REFUSED_OPTOUT = "refused_optout"
# Not dev mode -- takeover is dev-only, refused.
REFUSED_PROD = "refused_prod"
# Inside a container the server IS the container -- skipped, nothing killed.
SKIPPED_CONTAINER = "skipped_container"


@dataclass
class TakeoverResult:
    """What a takeover attempt did, so each caller can react in its own idiom."""

    status: str
    port: int
    killed: list[int] = field(default_factory=list)
    message: str = ""

    @property
    def reclaimed(self) -> bool:
        """True when a Tina4 holder was signalled (the port is being freed)."""
        return self.status == KILLED

    @property
    def refused(self) -> bool:
        """True when a holder was left running on purpose (foreign/opt-out/prod)."""
        return self.status in (REFUSED_FOREIGN, REFUSED_OPTOUT, REFUSED_PROD)


# ── environment resolution (the real gate + opt-out) ──────────────────────

def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "yes", "on")


def is_dev() -> bool:
    """Dev mode = ``TINA4_DEBUG`` truthy. Takeover runs only in dev."""
    return _is_truthy(os.environ.get("TINA4_DEBUG"))


def no_takeover_opted_out() -> bool:
    """True when takeover is disabled via ``TINA4_NO_TAKEOVER``."""
    return _is_truthy(os.environ.get("TINA4_NO_TAKEOVER"))


# ── container guard (unchanged behaviour, one home) ───────────────────────

def in_container() -> bool:
    """True when this process is running inside a container.

    Reclaiming a port makes sense on a dev machine, where a previous
    ``tina4 serve`` may still hold it. Inside a container the server IS the
    container, so there is never a stale sibling to reclaim from.
    """
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8", errors="replace") as fh:
            blob = fh.read()
        return "docker" in blob or "containerd" in blob or "kubepods" in blob
    except OSError:
        return False


# ── PID safety filter (unchanged; foreign PIDs are still SELECTED here -- ──
#    identity is a separate, later gate) ─────────────────────────────────────

def selectable_pids(lsof_output: str, me: int, my_group: int | None = None) -> list[int]:
    """The PIDs from ``lsof -ti`` output that are safe to signal.

    Pure so the safety rule can be tested directly. An unvalidated parse is a
    footgun with real teeth: when ``lsof`` prints a different shape than ``-ti``
    implies, a non-numeric field coerces to 0, and signalling PID 0 sends the
    signal to EVERY process in the caller's own process group -- the server kills
    itself.

    So: accept only all-digit tokens, and never PID 0 (our process group),
    PID 1 (init), ourselves, or our own process group. This is the PID-SAFETY
    gate only; whether a survivor is actually a Tina4 server is the SEPARATE
    identity check in :func:`take_over_port`.
    """
    pids: list[int] = []
    for token in lsof_output.split():
        if not token.isdigit():
            continue              # never coerce junk into a PID
        pid = int(token)
        if pid <= 1 or pid == me:
            continue              # 0 = our process group, 1 = init, me = suicide
        if my_group is not None and pid == my_group:
            continue
        if pid not in pids:
            pids.append(pid)
    return pids


# ── the Tina4 identity: a per-port PID file the dev server writes ──────────

def runtime_dir(base_dir: str | None = None) -> str:
    """Directory holding the per-port PID files (default ``<cwd>/data``)."""
    return base_dir if base_dir is not None else os.path.join(os.getcwd(), "data")


def pidfile_path(port: int, base_dir: str | None = None) -> str:
    """Absolute path of the PID file a Tina4 dev server writes for *port*."""
    return os.path.join(runtime_dir(base_dir), f".tina4-serve-{port}.pid")


def write_pidfile(port: int, base_dir: str | None = None, pid: int | None = None) -> None:
    """Record THIS process as the Tina4 dev server holding *port*.

    Called once by the server after it binds, so a later ``tina4 serve`` can
    identify it as reclaimable. Best-effort: a write failure never crashes boot.
    """
    directory = runtime_dir(base_dir)
    try:
        os.makedirs(directory, exist_ok=True)
        with open(pidfile_path(port, base_dir), "w", encoding="utf-8") as fh:
            fh.write(str(pid if pid is not None else os.getpid()))
    except OSError:
        pass  # identity is a convenience; never let it break the server


def read_pidfile(port: int, base_dir: str | None = None) -> int | None:
    """The PID a Tina4 dev server recorded for *port*, or None if none/garbage."""
    try:
        with open(pidfile_path(port, base_dir), "r", encoding="utf-8") as fh:
            token = fh.read().strip().split()[0]
        return int(token) if token.isdigit() else None
    except (OSError, IndexError, ValueError):
        return None


def remove_pidfile(port: int, base_dir: str | None = None) -> None:
    """Drop the PID file for *port* (clean shutdown, or after reclaiming it)."""
    try:
        os.remove(pidfile_path(port, base_dir))
    except OSError:
        pass


# ── locating the holder(s) ────────────────────────────────────────────────

def _port_holders(port: int) -> list[str]:
    """Raw ``lsof -ti`` (POSIX) / ``netstat`` (Windows) PID tokens for *port*."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        tokens: list[str] = []
        for line in result.stdout.splitlines():
            if f":{port}" in line and ("LISTENING" in line or "ESTABLISHED" in line):
                parts = line.split()
                if parts and parts[-1].isdigit():
                    tokens.append(parts[-1])
        return tokens
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.split()
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        try:
            result = subprocess.run(
                ["fuser", f"{port}/tcp"], capture_output=True, text=True, timeout=5
            )
            return result.stdout.split()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
    return []


# ── the ONE takeover entry point (CLI + runtime both call this) ────────────

def take_over_port(
    port: int,
    *,
    dev: bool,
    no_takeover: bool,
    base_dir: str | None = None,
    grace: float = 0.5,
) -> TakeoverResult:
    """Reclaim *port* ONLY from an identity-confirmed Tina4 dev server.

    The single guarded path for both the CLI (`tina4 serve`) and the runtime
    bind-failure fallback. Order of guards:

    1. Opt-out (`no_takeover`)   -> REFUSED_OPTOUT, nothing killed.
    2. Not dev (`dev` is False)  -> REFUSED_PROD, nothing killed.
    3. In a container            -> SKIPPED_CONTAINER, nothing killed.
    4. No holder                 -> NOTHING (bind may proceed).
    5. Holder is not Tina4       -> REFUSED_FOREIGN, nothing killed.
    6. Holder IS Tina4           -> SIGTERM it, drop its PID file -> KILLED.

    ``dev`` and ``no_takeover`` are passed in so this stays pure and directly
    testable; the callers resolve them from :func:`is_dev` / :func:`no_takeover_opted_out`.
    """
    if no_takeover:
        return TakeoverResult(
            REFUSED_OPTOUT, port,
            message=(f"Port {port} is in use and takeover is disabled "
                     f"(TINA4_NO_TAKEOVER/--no-kill) -- free it or choose another port."),
        )
    if not dev:
        return TakeoverResult(
            REFUSED_PROD, port,
            message=(f"Port {port} is in use; takeover is disabled outside dev mode "
                     f"-- free it or choose another port."),
        )
    if in_container():
        return TakeoverResult(SKIPPED_CONTAINER, port)

    tokens = _port_holders(port)
    if not tokens or not any(t.isdigit() for t in tokens):
        return TakeoverResult(NOTHING, port)

    me = os.getpid()
    my_group = os.getpgrp() if hasattr(os, "getpgrp") else None
    holders = selectable_pids(" ".join(tokens), me, my_group)
    if not holders:
        return TakeoverResult(NOTHING, port)

    recorded = read_pidfile(port, base_dir)
    tina4_holders = [pid for pid in holders if recorded is not None and pid == recorded]

    if not tina4_holders:
        return TakeoverResult(
            REFUSED_FOREIGN, port,
            message=(f"Port {port} is held by a non-Tina4 process "
                     f"-- free it or choose another port."),
        )

    killed: list[int] = []
    for pid in tina4_holders:
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except (ProcessLookupError, PermissionError):
            pass

    if not killed:
        return TakeoverResult(NOTHING, port)

    remove_pidfile(port, base_dir)
    if grace > 0:
        import time
        time.sleep(grace)
    return TakeoverResult(
        KILLED, port, killed=killed,
        message=f"Reclaimed port {port} from Tina4 dev server (PID: "
                f"{', '.join(str(p) for p in killed)}).",
    )
