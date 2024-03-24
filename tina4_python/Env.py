#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import os

from dotenv import load_dotenv


# check .env for information
def load_env(path: str = '.env'):
    if not os.path.isfile(path):
        with open(path, 'w') as f:
            f.write("# Project Settings\n")
            f.write("PROJECT_NAME=\"My Project\"\n")
            f.write("VERSION=1.0.0\n")
            f.write("TINA4_LANGUAGE=en\n")
            f.write("TINA4_SECRET=ABCDEF\n")
            f.write("TINA4_DEBUG_LEVEL=6\n")
    # Load the .env
    load_dotenv(path)
    # check for defaults we need
    if not "TINA4_LANGUAGE" in os.environ:
        with open(path, 'a') as f:
            f.write("TINA4_LANGUAGE=en\n")
    if not "TINA4_DEBUG_LEVEL" in os.environ:
        with open(path, 'a') as f:
            f.write("TINA4_DEBUG_LEVEL=6\n")
    if not "TINA4_SECRET" in os.environ:
        with open(path, 'a') as f:
            f.write("TINA4_SECRET=ABCDEF\n")
