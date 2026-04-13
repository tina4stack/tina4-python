#!/usr/bin/env bash
# Tina4 Store Demo — One-command setup (macOS / Linux)
# Usage: bash setup.sh
#
# Windows users: see setup.bat
set -euo pipefail

echo "=== Tina4 Store (Python) Setup ==="
echo ""

# Check Python
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "ERROR: Python not found. Install Python 3.12+ first."
    echo "  macOS:   brew install python"
    echo "  Ubuntu:  sudo apt install python3 python3-venv"
    exit 1
fi

PY_VER=$($PY --version 2>&1)
echo "[OK] $PY_VER"

# Create venv if missing
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    $PY -m venv .venv
    echo "[OK] Virtual environment created"
else
    echo "[OK] Virtual environment exists"
fi

# Install from local framework source
echo "Installing tina4-python from local source..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "[OK] tina4-python installed"

# Create .env if missing
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[OK] Created .env from .env.example"
else
    echo "[OK] .env exists"
fi

# Create data directories
mkdir -p data data/sessions data/queue data/mailbox src/public/uploads
echo "[OK] Data directories ready"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Start the server:"
echo "  .venv/bin/python app.py"
echo ""
echo "Then open: http://localhost:7146"
echo ""
echo "Admin login: admin@tina4store.com / admin123"
