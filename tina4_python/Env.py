#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import os
import hashlib
from datetime import datetime
from dotenv import load_dotenv
from tina4_python.Debug import Debug


# check .env for information
def load_env(path: str = '.env'):
    if not os.path.isfile(path):
        current_time = datetime.now()
        result = hashlib.md5(current_time.strftime("%A,%d %B %Y").encode())
        with open(path, 'w') as f:
            f.write("# Project Settings\n")
            f.write("PROJECT_NAME=\"My Project\"\n")
            f.write("VERSION=1.0.0\n")
            f.write("TINA4_LANGUAGE=en\n")
            f.write("API_KEY="+result.hexdigest()+"\n")
            f.write("TINA4_DEBUG_LEVEL=[TINA4_LOG_ALL]\n")
    # Load the .env
    load_dotenv(path)
    Debug.info(os.environ)
    # check for defaults we need
    if "TINA4_LANGUAGE" not in os.environ:
        with open(path, 'a') as f:
            f.write("TINA4_LANGUAGE=en\n")
    if "TINA4_DEBUG_LEVEL" not in os.environ:
        with open(path, 'a') as f:
            f.write("TINA4_DEBUG_LEVEL=[\"ALL\"]\n")
    if "API_KEY" not in os.environ:
        current_time = datetime.now()
        result = hashlib.md5(current_time.strftime("%A,%d %B %Y").encode())
        with open(path, 'a') as f:
            f.write("API_KEY="+result.hexdigest()+"\n")
