#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import tina4_python.Constant as Constant
from datetime import datetime


class Debug:
    def __init__(self, message, debug_level=Constant.DEBUG_INFO):
        now = datetime.now()
        print(now.strftime("%Y-%m-%d %H:%M:%S"), ":", message)
        pass
