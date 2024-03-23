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
            f.write("[Project]")
            f.write("\n")
    load_dotenv(path)
