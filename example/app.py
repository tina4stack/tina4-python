"""Tina4 Python example application."""
from tina4_python.core import run

# Start the server — routes are auto-discovered from src/routes/
# Host/port resolved via: CLI flag > ENV var (HOST/PORT) > default (0.0.0.0:7145)
if __name__ == "__main__":
    run()
