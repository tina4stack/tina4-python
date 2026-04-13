#!/usr/bin/env bash
# Tina4 Store Demo — One-command setup (macOS / Linux)
# Usage: bash setup.sh
#
# Windows users: see setup.bat
set -euo pipefail

echo "=== Tina4 Store (Python) Setup ==="
echo ""

# Prefer uv (matches framework tooling)
if command -v uv &>/dev/null; then
    echo "[OK] uv found"
    uv sync
    echo "[OK] Dependencies installed"
else
    # Fallback: find Python >= 3.12 and use pip
    PY=""
    for candidate in python3.13 python3.12 python3 python; do
        if command -v "$candidate" &>/dev/null; then
            ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
                PY="$candidate"
                break
            fi
        fi
    done

    if [ -z "$PY" ]; then
        echo "ERROR: Python 3.12+ not found. Install uv or Python 3.12+."
        echo "  uv:      curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo "  macOS:   brew install python@3.13"
        echo "  Ubuntu:  sudo apt install python3.13 python3.13-venv"
        exit 1
    fi

    PY_VER=$($PY --version 2>&1)
    echo "[OK] $PY_VER"

    if [ ! -d .venv ]; then
        echo "Creating virtual environment..."
        $PY -m venv .venv
        echo "[OK] Virtual environment created"
    else
        echo "[OK] Virtual environment exists"
    fi

    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -e ..
    echo "[OK] tina4-python installed"
fi

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
if command -v uv &>/dev/null; then
    echo "  uv run python app.py"
else
    echo "  .venv/bin/python app.py"
fi
echo ""
echo "Then open: http://localhost:7145"
echo ""
echo "Admin login: admin@tina4store.com / admin123"
