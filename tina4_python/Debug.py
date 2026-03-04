#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Centralised logging and debug output for Tina4 Python.

This module provides a dual-output logging system:

- **Console handler** -- coloured output whose verbosity is controlled by the
  ``TINA4_DEBUG_LEVEL`` environment variable (default ``All``).
- **File handler** -- a rotating log file at ``./logs/debug.log`` that always
  captures *all* levels (DEBUG and above), regardless of the console setting.

The module exposes a single callable singleton, ``Debug``, which can be used
either as a function or via its convenience static methods::

    from tina4_python.Debug import Debug

    Debug("Server started on port", port)       # default INFO level
    Debug.error("Something went wrong:", err)   # ERROR level
    Debug.warning("Disk space low")             # WARNING level
    Debug.debug("Verbose trace info")           # DEBUG level

Valid values for the ``TINA4_DEBUG_LEVEL`` env var (case-insensitive):
``All``, ``Debug``, ``Info``, ``Warning``, ``Error``.
"""

__all__ = ["Debug", "setup_logging"]

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

from tina4_python.Constant import (
    TINA4_LOG_ALL,
    TINA4_LOG_DEBUG,
    TINA4_LOG_INFO,
    TINA4_LOG_WARNING,
    TINA4_LOG_ERROR,
)
from tina4_python.ShellColors import ShellColors


class ColoredFormatter(logging.Formatter):
    """Custom logging formatter that applies ANSI colour codes to log output.

    Each log level is mapped to a colour from ``ShellColors`` so that console
    output is easy to scan visually.  Both the message body and the level name
    are wrapped in the appropriate colour escape sequences.

    Attributes:
        LEVEL_COLORS (dict): Mapping of ``logging`` level constants to ANSI
            colour escape strings.
    """

    LEVEL_COLORS = {
        logging.DEBUG: ShellColors.green,
        logging.INFO: ShellColors.cyan,
        logging.WARNING: ShellColors.bright_yellow,
        logging.ERROR: ShellColors.bright_red,
        logging.CRITICAL: ShellColors.bright_red + ShellColors.bold,
    }

    def format(self, record):
        """Format a log record with ANSI colour codes.

        Args:
            record (logging.LogRecord): The log record to format.

        Returns:
            str: The formatted, colour-coded log string.
        """
        color = self.LEVEL_COLORS.get(record.levelno, "")
        record.msg = f"{color}{record.msg}{ShellColors.end}"
        record.levelname = f"{color}{record.levelname}{ShellColors.end}"
        return super().format(record)


def setup_logging():
    """Initialise the ``TINA4`` logger with console and file handlers.

    This function is idempotent -- if the logger already has handlers
    attached it returns immediately, so it is safe to call multiple times.

    Behaviour:

    * Reads the ``TINA4_DEBUG_LEVEL`` environment variable (falling back to
      ``All``) and maps it to a Python ``logging`` level for the console handler.
    * Creates a ``StreamHandler`` on ``sys.stdout`` with coloured output via
      ``ColoredFormatter``.
    * Creates a ``RotatingFileHandler`` at ``./logs/debug.log`` (5 MB per file,
      10 backups) that always logs at ``DEBUG`` level.
    """
    logger = logging.getLogger("TINA4")
    if logger.handlers:
        return

    raw = str(os.getenv("TINA4_DEBUG_LEVEL", TINA4_LOG_ALL))
    clean = "".join(c for c in raw if c.isalnum() or c == "_").upper()

    level_map = {
        "ALL": logging.DEBUG, "TINA4_LOG_ALL": logging.DEBUG,
        "DEBUG": logging.DEBUG, "TINA4_LOG_DEBUG": logging.DEBUG,
        "INFO": logging.INFO, "TINA4_LOG_INFO": logging.INFO,
        "WARN": logging.WARNING, "WARNING": logging.WARNING, "TINA4_LOG_WARNING": logging.WARNING,
        "ERROR": logging.ERROR, "TINA4_LOG_ERROR": logging.ERROR,
    }
    console_level = level_map.get(clean, logging.INFO)

    # Root logger = console level → blocks lower messages on console
    logger.setLevel(console_level)

    # Console – respects the level
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(ColoredFormatter(
        fmt="%(levelname)-8s: %(asctime)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(console)

    # File – ALWAYS logs everything (DEBUG and above)
    os.makedirs("./logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        "./logs/debug.log",
        maxBytes=5*1024*1024,
        backupCount=10,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(levelname)-8s: %(asctime)s: %(message)s"
    ))
    logger.addHandler(file_handler)


class _Debug:
    """Callable singleton that wraps the ``TINA4`` logger.

    Instances of this class act as both a function and an object with static
    convenience methods (``info``, ``error``, ``warning``, ``debug``).
    The module creates a single global instance named ``Debug`` (see bottom
    of module) which is the public API.

    Examples::

        Debug("Processing request", request_id)            # INFO (default)
        Debug("trace data", data, level=TINA4_LOG_DEBUG)   # explicit level
        Debug.error("Unexpected failure:", exc)             # static shortcut
    """

    def __init__(self):
        """Create the debug wrapper around the ``TINA4`` logger."""
        self.logger = logging.getLogger("TINA4")

    def __call__(self, *messages, level=TINA4_LOG_INFO):
        """Log one or more values at the given level.

        All positional arguments are stringified and joined with spaces.

        Args:
            *messages: Values to log.  Each is converted to ``str`` and
                concatenated with a single space separator.
            level (str): One of the ``TINA4_LOG_*`` constants from
                ``tina4_python.Constant``.  Defaults to ``TINA4_LOG_INFO``.
        """
        msg = " ".join(str(m) for m in messages)
        mapping = {
            TINA4_LOG_ALL:     self.logger.debug,
            TINA4_LOG_DEBUG:   self.logger.debug,
            TINA4_LOG_INFO:    self.logger.info,
            TINA4_LOG_WARNING: self.logger.warning,
            TINA4_LOG_ERROR:   self.logger.error,
        }
        func = mapping.get(level, self.logger.info)
        func(msg)

    @staticmethod
    def info(*m):
        """Log a message at INFO level.

        Args:
            *m: Values to log.  Each is converted to ``str`` and joined
                with a single space.
        """
        logging.getLogger("TINA4").info(" ".join(str(x) for x in m))

    @staticmethod
    def error(*m):
        """Log a message at ERROR level.

        Args:
            *m: Values to log.  Each is converted to ``str`` and joined
                with a single space.
        """
        logging.getLogger("TINA4").error(" ".join(str(x) for x in m))

    @staticmethod
    def warning(*m):
        """Log a message at WARNING level.

        Args:
            *m: Values to log.  Each is converted to ``str`` and joined
                with a single space.
        """
        logging.getLogger("TINA4").warning(" ".join(str(x) for x in m))

    @staticmethod
    def debug(*m):
        """Log a message at DEBUG level.

        Args:
            *m: Values to log.  Each is converted to ``str`` and joined
                with a single space.
        """
        logging.getLogger("TINA4").debug(" ".join(str(x) for x in m))


# Global callable instance — created after class is defined
Debug = _Debug()

__all__ = ["Debug"]
