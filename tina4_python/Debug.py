#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501

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
    LEVEL_COLORS = {
        logging.DEBUG: ShellColors.green,
        logging.INFO: ShellColors.cyan,
        logging.WARNING: ShellColors.bright_yellow,
        logging.ERROR: ShellColors.bright_red,
        logging.CRITICAL: ShellColors.bright_red + ShellColors.bold,
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, "")
        record.msg = f"{color}{record.msg}{ShellColors.end}"
        record.levelname = f"{color}{record.levelname}{ShellColors.end}"
        return super().format(record)


def setup_logging():
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
    def __init__(self):
        self.logger = logging.getLogger("TINA4")

    def __call__(self, *messages, level=TINA4_LOG_INFO):
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
        logging.getLogger("TINA4").info(" ".join(str(x) for x in m))

    @staticmethod
    def error(*m):
        logging.getLogger("TINA4").error(" ".join(str(x) for x in m))

    @staticmethod
    def warning(*m):
        logging.getLogger("TINA4").warning(" ".join(str(x) for x in m))

    @staticmethod
    def debug(*m):
        logging.getLogger("TINA4").debug(" ".join(str(x) for x in m))


# Global callable instance — created after class is defined
Debug = _Debug()

__all__ = ["Debug"]
