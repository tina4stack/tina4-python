#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
"""Environment variable management for Tina4 projects.

Handles loading (and bootstrapping) of a ``.env`` file so that
project-level configuration is available through ``os.environ``
throughout the application lifetime.

When the specified ``.env`` file does not yet exist, :func:`load_env`
creates it with sensible defaults (``PROJECT_NAME``, ``VERSION``,
``TINA4_LANGUAGE``, ``API_KEY``, and ``TINA4_DEBUG_LEVEL``).  After
loading, any required keys that are still missing are appended to the
file automatically.
"""

__all__ = ["load_env"]

import os
import hashlib
from datetime import datetime
from dotenv import load_dotenv
from tina4_python.Debug import Debug


def load_env(path: str = '.env'):
    """Load environment variables from a ``.env`` file into ``os.environ``.

    If the file at *path* does not exist it is created with default
    project settings (``PROJECT_NAME``, ``VERSION``, ``TINA4_LANGUAGE``,
    ``API_KEY``, ``TINA4_DEBUG_LEVEL``).  After loading, any required
    keys that are still absent (``TINA4_LANGUAGE``, ``TINA4_DEBUG_LEVEL``,
    ``API_KEY``) are appended to the file so they are available on
    subsequent runs.

    The ``API_KEY`` default is an MD5 hex-digest derived from the
    current date, providing a unique-per-day value for new projects.

    Args:
        path: Filesystem path to the ``.env`` file.  Defaults to
            ``".env"`` in the current working directory.

    Returns:
        None.  Side-effects: populates ``os.environ`` via
        ``dotenv.load_dotenv`` and may create or append to the file at
        *path*.
    """
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
            f.write("\n# MCP Server (AI tool integration)\n")
            f.write("# Auto-enabled in debug mode. Set to true for production.\n")
            f.write("#TINA4_MCP=true\n")
            f.write("#TINA4_MCP_PATH=/__mcp\n")
            f.write("#TINA4_MCP_LOGS=true\n")
            f.write("#TINA4_MCP_FILES_READ=true\n")
            f.write("#TINA4_MCP_FILES_WRITE=true\n")
            f.write("#TINA4_MCP_CODE_WRITE=false\n")
            f.write("#TINA4_MCP_DB_READ=true\n")
            f.write("#TINA4_MCP_DB_WRITE=false\n")
            f.write("#TINA4_MCP_QUEUE=true\n")
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
