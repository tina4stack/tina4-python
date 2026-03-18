import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tina4_python
from tina4_python import run_web_server

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7148)
