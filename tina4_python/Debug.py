#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os
import sys
import logging
import logging.config
from logging.handlers import RotatingFileHandler
import tina4_python.Constant as Constant
from tina4_python.ShellColors import ShellColors
from datetime import datetime


LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(levelname)s: %(asctime)s: %(message)s',
        },
    },
    'handlers': {
        'stdout': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'default',
        },
    },
    'loggers': {
        'TINA4': {
            'handlers': ['stdout'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}

class Debug:

    @staticmethod
    def info(*args, **kwargs):
        args += (Constant.TINA4_LOG_INFO,)
        Debug(*args, **kwargs)

    @staticmethod
    def error(*args, **kwargs):
        args += (Constant.TINA4_LOG_ERROR,)
        Debug(*args, **kwargs)

    @staticmethod
    def debug(*args, **kwargs):
        args += (Constant.TINA4_LOG_DEBUG,)
        Debug(*args, **kwargs)

    @staticmethod
    def warning(*args, **kwargs):
        args += (Constant.TINA4_LOG_WARNING,)
        Debug(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        now = datetime.now()
        debug_level = os.getenv("TINA4_DEBUG_LEVEL", Constant.TINA4_LOG_ALL)

        logging.config.dictConfig(LOGGING_CONFIG)
        if debug_level == Constant.TINA4_LOG_ALL or debug_level == Constant.TINA4_LOG_DEBUG:
            logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
        elif debug_level == Constant.TINA4_LOG_INFO:
            logging.basicConfig(stream=sys.stdout, level=logging.INFO)
        elif debug_level == Constant.TINA4_LOG_ERROR:
            logging.basicConfig(stream=sys.stdout, level=logging.ERROR)
        elif debug_level == Constant.TINA4_LOG_WARNING:
            logging.basicConfig(stream=sys.stdout, level=logging.WARNING)

        params = [now.strftime("%Y-%m-%d %H:%M:%S") + ":"]
        for value in args:
            if value in [Constant.TINA4_LOG_ALL, Constant.TINA4_LOG_DEBUG, Constant.TINA4_LOG_INFO,
                         Constant.TINA4_LOG_ERROR, Constant.TINA4_LOG_WARNING]:
                debug_level = value
            else:
                params.append(value)

        file_name = "debug.log"
        if "file_name" in kwargs:
            file_name = kwargs["file_name"]

        formatter = logging.Formatter("%(levelname)s: %(asctime)s: %(message)s")
        logger = logging.getLogger('TINA4')
        logger.setLevel(logging.DEBUG)

        handler = RotatingFileHandler("."+os.sep+"logs"+os.sep+file_name, maxBytes=1024*1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        if (os.getenv("TINA4_DEBUG_LEVEL", [Constant.TINA4_LOG_ALL]) == "[TINA4_LOG_ALL]"
                or debug_level in os.getenv("TINA4_DEBUG_LEVEL", [Constant.TINA4_LOG_ALL])):

            log_level = 0
            # choose the color
            color = ShellColors.bright_blue

            if debug_level == Constant.TINA4_LOG_INFO:
                color = ShellColors.cyan
                log_level = 20

            elif debug_level == Constant.TINA4_LOG_DEBUG:
                color = ShellColors.bright_magenta
                log_level = 10

            elif debug_level == Constant.TINA4_LOG_ERROR:
                color = ShellColors.bright_red
                log_level = 40

            elif debug_level == Constant.TINA4_LOG_WARNING:
                color = ShellColors.bright_yellow
                log_level = 30

            end = ShellColors.end

            logger.log(log_level, f"{color} ".join(str(param) for param in params[1:]).strip()+f"{end} ")

        handler.flush()
        logger.removeHandler(handler)
        handler.close()
