#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import os

import tina4_python.Constant as Constant
from datetime import datetime


class Debug:

    def __init__(self, *args, **kwargs):
        now = datetime.now()
        debug_level = Constant.TINA4_LOG_ALL
        params = [now.strftime("%Y-%m-%d %H:%M:%S") + ":"]
        for value in args:
            if value in [Constant.TINA4_LOG_ALL, Constant.TINA4_LOG_DEBUG, Constant.TINA4_LOG_INFO,
                         Constant.TINA4_LOG_ERROR, Constant.TINA4_LOG_WARNING]:
                debug_level = value
            else:
                params.append(value)

        if (os.getenv("TINA4_DEBUG_LEVEL", [Constant.TINA4_LOG_ALL]) == "[TINA4_LOG_ALL]"
                or debug_level in os.getenv("TINA4_DEBUG_LEVEL", [Constant.TINA4_LOG_ALL])):
            print(f"{debug_level:5}:", "", end="")
            for output in params:
                print(output, "", end="")

            print()
        pass
