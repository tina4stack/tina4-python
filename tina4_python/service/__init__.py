# Tina4 Service Runner — Background services with cron scheduling and daemon mode.
"""
Zero-dependency background service runner using threading.

    from tina4_python.service import ServiceRunner

    runner = ServiceRunner()
    runner.register("cleanup", cleanup_handler, cron="0 3 * * *")
    runner.register("heartbeat", heartbeat_handler, interval=30)
    runner.start()

Supports:
    - Cron expressions (minute hour day-of-month month day-of-week)
    - Simple interval (every N seconds)
    - Daemon mode (handler manages its own loop)
    - Auto-discovery from src/services/
    - Graceful shutdown
    - Max retries on crash
"""
import os
import sys
import time
import threading
import importlib.util
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Lazy import of Log — avoids circular imports at module load time
# ---------------------------------------------------------------------------

_log = None


def _get_log():
    global _log
    if _log is None:
        try:
            from tina4_python.debug import Log
            _log = Log
        except ImportError:
            # Fallback: print-based logger when debug module is unavailable
            class _FallbackLog:
                @staticmethod
                def debug(msg, **kw):
                    print(f"[DEBUG] {msg}", kw if kw else "")

                @staticmethod
                def info(msg, **kw):
                    print(f"[INFO]  {msg}", kw if kw else "")

                @staticmethod
                def warning(msg, **kw):
                    print(f"[WARN]  {msg}", kw if kw else "")

                @staticmethod
                def error(msg, **kw):
                    print(f"[ERROR] {msg}", kw if kw else "")

            _log = _FallbackLog()
    return _log


# ---------------------------------------------------------------------------
# Cron helpers
# ---------------------------------------------------------------------------

def parse_cron(expression: str) -> dict:
    """Parse a 5-field cron expression into its components.

    Args:
        expression: Cron string, e.g. ``"*/5 * * * *"``.

    Returns:
        Dict with keys ``minute``, ``hour``, ``day``, ``month``, ``weekday``,
        each containing the raw field string.  Returns an empty dict on
        invalid input.
    """
    fields = expression.strip().split()
    if len(fields) != 5:
        return {}
    return {
        "minute": fields[0],
        "hour": fields[1],
        "day": fields[2],
        "month": fields[3],
        "weekday": fields[4],
    }


def _field_matches(field: str, value: int) -> bool:
    """Check if a single cron field matches a given value.

    Supports:
        *       — wildcard (matches any value)
        */N     — step (every N units)
        N       — exact value
        N-M     — range
        N-M/S   — range with step
        N,M,O   — list of values
    """
    # Wildcard
    if field == "*":
        return True

    # List  (e.g. "1,3,5") — recurse into each element
    if "," in field:
        return any(_field_matches(part.strip(), value) for part in field.split(","))

    # Step on wildcard  (e.g. "*/5")
    if field.startswith("*/"):
        step = int(field[2:])
        return step > 0 and value % step == 0

    # Range with optional step  (e.g. "1-5" or "1-5/2")
    if "-" in field:
        range_part, _, step_part = field.partition("/")
        lo_str, hi_str = range_part.split("-", 1)
        lo, hi = int(lo_str), int(hi_str)
        step = int(step_part) if step_part else 1
        if value < lo or value > hi:
            return False
        return (value - lo) % step == 0

    # Exact value
    return int(field) == value


def cron_matches(expression: str, now: datetime | None = None) -> bool:
    """Check if a cron expression matches the current (or given) time.

    Args:
        expression: 5-field cron string.
        now: Optional datetime to test against (defaults to ``datetime.now()``).

    Returns:
        ``True`` if the expression matches, ``False`` otherwise (including
        when the expression is invalid).
    """
    fields = expression.strip().split()
    if len(fields) != 5:
        _get_log().warning("Invalid cron expression", expression=expression)
        return False

    if now is None:
        now = datetime.now()

    current = [
        now.minute,           # 0-59
        now.hour,             # 0-23
        now.day,              # 1-31
        now.month,            # 1-12
        now.weekday() + 1 if now.weekday() < 6 else 0,  # 0=Sun … 6=Sat
    ]
    # Python weekday(): Mon=0 … Sun=6  →  cron: Sun=0 … Sat=6
    # Correction: Sun(6 in Python) → 0, Mon(0) → 1, … Sat(5) → 6
    current[4] = (now.weekday() + 1) % 7

    return all(_field_matches(fields[i], current[i]) for i in range(5))


# ---------------------------------------------------------------------------
# Service context — passed into every handler invocation
# ---------------------------------------------------------------------------

class ServiceContext:
    """Runtime context passed to service handler functions."""

    __slots__ = ("name", "running", "last_run", "stop_event", "log")

    def __init__(self, name: str, stop_event: threading.Event):
        self.name: str = name
        self.running: bool = True
        self.last_run: float = 0.0
        self.stop_event: threading.Event = stop_event
        self.log = _get_log()


# ---------------------------------------------------------------------------
# ServiceRunner
# ---------------------------------------------------------------------------

class ServiceRunner:
    """Manages long-running background services with cron scheduling and daemon mode."""

    def __init__(self):
        self.services: list[dict] = []
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._started = False

    # -- Registration -------------------------------------------------------

    def register(self, name: str, handler: callable, interval: int = 60,
                 cron: str = None, daemon: bool = False, max_retries: int = 3):
        """Register a background service.

        Args:
            name: Human-readable service name (used in logs).
            handler: Callable that receives a :class:`ServiceContext`.
            interval: Seconds between runs (ignored when *cron* is set).
            cron: Cron expression, e.g. ``"*/5 * * * *"``.
            daemon: If ``True`` the handler manages its own loop; the runner
                    calls it once and does not reschedule.
            max_retries: Number of consecutive crash restarts before giving up.
        """
        self.services.append({
            "name": name,
            "handler": handler,
            "interval": interval,
            "cron": cron,
            "daemon": daemon,
            "max_retries": max_retries,
            "retries": 0,
            "running": False,
            "last_run": None,
            "started_at": None,
        })

    # -- Lifecycle ----------------------------------------------------------

    def start(self):
        """Start all registered services in background threads."""
        if self._started:
            _get_log().warning("ServiceRunner already started")
            return

        self._stop_event.clear()
        self._started = True

        for svc in self.services:
            ctx = ServiceContext(svc["name"], self._stop_event)
            t = threading.Thread(
                target=self._run_service,
                args=(svc, ctx),
                name=f"svc-{svc['name']}",
                daemon=True,
            )
            self._threads.append(t)
            svc["running"] = True
            svc["started_at"] = datetime.now().isoformat()
            t.start()
            _get_log().info("Service started", name=svc["name"])

    def stop(self):
        """Stop all running services gracefully."""
        _get_log().info("Stopping all services")
        self._stop_event.set()

        for svc in self.services:
            svc["running"] = False

        # Give threads a moment to finish
        for t in self._threads:
            t.join(timeout=5)

        self._threads.clear()
        self._started = False
        _get_log().info("All services stopped")

    def status(self) -> list[dict]:
        """Return status of all registered services.

        Returns:
            A list of dicts, each containing ``name``, ``running``,
            ``last_run``, ``retries``, ``started_at``, ``daemon``, ``cron``,
            and ``interval``.
        """
        return [
            {
                "name": svc["name"],
                "running": svc["running"],
                "last_run": svc["last_run"],
                "retries": svc["retries"],
                "started_at": svc["started_at"],
                "daemon": svc["daemon"],
                "cron": svc["cron"],
                "interval": svc["interval"],
            }
            for svc in self.services
        ]

    # -- Discovery ----------------------------------------------------------

    def discover(self, service_dir: str = "") -> list[str]:
        """Auto-discover service files from a directory.

        Each ``.py`` file in *service_dir* must define a module-level dict
        named ``service`` with at least ``name`` (str) and ``handler``
        (callable).  Optional keys: ``interval``, ``cron``, ``daemon``,
        ``max_retries``.

        Args:
            service_dir: Path to scan.  Defaults to the ``TINA4_SERVICE_DIR``
                         env var, or ``src/services``.

        Returns:
            List of discovered service names.
        """
        if not service_dir:
            service_dir = os.environ.get("TINA4_SERVICE_DIR", "src/services")

        svc_path = Path(service_dir)
        if not svc_path.is_dir():
            return []

        discovered: list[str] = []

        for py_file in sorted(svc_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    f"tina4_service_{py_file.stem}", str(py_file)
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

                config = getattr(mod, "service", None)
                if not isinstance(config, dict):
                    _get_log().warning(
                        "Service file missing 'service' dict",
                        file=str(py_file),
                    )
                    continue

                if "name" not in config or "handler" not in config:
                    _get_log().warning(
                        "Service dict missing 'name' or 'handler'",
                        file=str(py_file),
                    )
                    continue

                self.register(
                    name=config["name"],
                    handler=config["handler"],
                    interval=config.get("interval", 60),
                    cron=config.get("cron"),
                    daemon=config.get("daemon", False),
                    max_retries=config.get("max_retries", 3),
                )
                discovered.append(config["name"])

            except Exception as exc:
                _get_log().error(
                    "Failed to load service file",
                    file=str(py_file),
                    error=str(exc),
                )

        return discovered

    # -- Internal -----------------------------------------------------------

    def _run_service(self, svc: dict, ctx: ServiceContext):
        """Main loop for a single service thread."""
        log = _get_log()
        retries = 0
        max_retries = svc["max_retries"]
        last_cron_minute = -1

        while not self._stop_event.is_set() and retries <= max_retries:
            try:
                # -- Daemon mode: call handler once, it manages its own loop --
                if svc["daemon"]:
                    svc["handler"](ctx)
                    break

                # -- Cron mode: check expression every second --
                if svc["cron"]:
                    now = datetime.now()
                    current_minute = now.minute
                    if current_minute != last_cron_minute and cron_matches(svc["cron"], now):
                        last_cron_minute = current_minute
                        svc["handler"](ctx)
                        ctx.last_run = time.time()
                        svc["last_run"] = datetime.now().isoformat()
                        retries = 0
                    # Sleep briefly then re-check
                    self._stop_event.wait(1)
                    continue

                # -- Interval mode: run, sleep, repeat --
                svc["handler"](ctx)
                ctx.last_run = time.time()
                svc["last_run"] = datetime.now().isoformat()
                retries = 0

                self._stop_event.wait(svc["interval"])

            except Exception as exc:
                retries += 1
                svc["retries"] = retries
                log.error(
                    "Service error",
                    name=svc["name"],
                    error=str(exc),
                    retry=retries,
                    max_retries=max_retries,
                )
                if retries > max_retries:
                    log.error(
                        "Service max retries exceeded, stopping",
                        name=svc["name"],
                    )
                    break
                # Back off briefly before retrying
                self._stop_event.wait(2)

        svc["running"] = False
        ctx.running = False
        log.info("Service thread exited", name=svc["name"])
