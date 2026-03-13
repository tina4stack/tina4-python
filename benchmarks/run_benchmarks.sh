#!/usr/bin/env bash
#
# Python Web Framework Benchmark Runner
# Tests: tina4 (default), tina4 (hypercorn), Flask, FastAPI, Django
# Tool: ApacheBench (ab)
#
# Usage: ./run_benchmarks.sh
#
set -euo pipefail

# Use the project venv if available
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv/bin"
if [ -f "$VENV/python3" ]; then
    export PATH="$VENV:$PATH"
    PYTHON="$VENV/python3"
else
    PYTHON="python3"
fi

REQUESTS=10000
CONCURRENCY=100
WARMUP=500
RESULTS_DIR="results"
SLEEP=3  # seconds to let server start

mkdir -p "$RESULTS_DIR"

DATE=$(date +%Y-%m-%d_%H%M%S)
SUMMARY="$RESULTS_DIR/summary_$DATE.txt"

echo "============================================" | tee "$SUMMARY"
echo " Python Web Framework Benchmark"             | tee -a "$SUMMARY"
echo " Date: $(date)"                               | tee -a "$SUMMARY"
echo " Requests: $REQUESTS  Concurrency: $CONCURRENCY" | tee -a "$SUMMARY"
echo " Python: $($PYTHON --version 2>&1)"           | tee -a "$SUMMARY"
echo " Machine: $(uname -m) $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo '')" | tee -a "$SUMMARY"
echo "============================================" | tee -a "$SUMMARY"
echo "" | tee -a "$SUMMARY"

# Helper: start server, benchmark, kill
run_benchmark() {
    local name="$1"
    local start_cmd="$2"
    local port="$3"
    local url="http://127.0.0.1:${port}/api/hello"
    local result_file="$RESULTS_DIR/${name}_${DATE}.txt"

    echo "--- $name (port $port) ---" | tee -a "$SUMMARY"

    # Start server in background
    eval "$start_cmd &"
    local pid=$!

    # Wait for server to be ready
    echo "  Starting server (pid $pid)..."
    for i in $(seq 1 15); do
        if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -q "200"; then
            break
        fi
        sleep 1
    done

    # Verify it's responding
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    if [ "$status" != "200" ]; then
        echo "  FAILED: Server not responding (status=$status)" | tee -a "$SUMMARY"
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        echo "" | tee -a "$SUMMARY"
        return
    fi

    # Warmup
    echo "  Warming up ($WARMUP requests)..."
    ab -n "$WARMUP" -c 10 "$url" > /dev/null 2>&1 || true

    # Benchmark
    echo "  Benchmarking ($REQUESTS requests, $CONCURRENCY concurrent)..."
    ab -n "$REQUESTS" -c "$CONCURRENCY" "$url" > "$result_file" 2>&1

    # Extract key metrics
    local rps mean_latency p50 p99 failed
    rps=$(grep "Requests per second" "$result_file" | awk '{print $4}')
    mean_latency=$(grep "Time per request.*\(mean\)" "$result_file" | head -1 | awk '{print $4}')
    p50=$(grep "  50%" "$result_file" | awk '{print $2}')
    p99=$(grep "  99%" "$result_file" | awk '{print $2}')
    failed=$(grep "Failed requests" "$result_file" | awk '{print $3}')

    printf "  Requests/sec:  %s\n" "${rps:-N/A}" | tee -a "$SUMMARY"
    printf "  Mean latency:  %s ms\n" "${mean_latency:-N/A}" | tee -a "$SUMMARY"
    printf "  P50 latency:   %s ms\n" "${p50:-N/A}" | tee -a "$SUMMARY"
    printf "  P99 latency:   %s ms\n" "${p99:-N/A}" | tee -a "$SUMMARY"
    printf "  Failed:        %s\n" "${failed:-0}" | tee -a "$SUMMARY"
    echo "  Full results:  $result_file" | tee -a "$SUMMARY"
    echo "" | tee -a "$SUMMARY"

    # Cleanup
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    sleep 1
}

# -------------------------------------------------------------------
# 1. tina4-python (built-in server via run_web_server / Hypercorn)
# -------------------------------------------------------------------
run_benchmark \
    "tina4_default" \
    "$PYTHON app_tina4.py" \
    8100

# -------------------------------------------------------------------
# 2. tina4-python (standalone Hypercorn)
# -------------------------------------------------------------------
if command -v hypercorn &>/dev/null; then
    run_benchmark \
        "tina4_hypercorn" \
        "hypercorn app_tina4_hypercorn:app --bind 0.0.0.0:8101" \
        8101
else
    echo "--- tina4_hypercorn: SKIPPED (hypercorn not found) ---" | tee -a "$SUMMARY"
    echo "" | tee -a "$SUMMARY"
fi

# -------------------------------------------------------------------
# 2b. tina4-python (Gunicorn + Uvicorn workers, 4 workers)
# -------------------------------------------------------------------
if command -v gunicorn &>/dev/null && $PYTHON -c "import uvicorn" 2>/dev/null; then
    run_benchmark \
        "tina4_gunicorn_uvicorn" \
        "gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8105 app_tina4_hypercorn:app" \
        8105
else
    echo "--- tina4_gunicorn_uvicorn: SKIPPED (gunicorn or uvicorn not found) ---" | tee -a "$SUMMARY"
    echo "" | tee -a "$SUMMARY"
fi

# -------------------------------------------------------------------
# 2c. tina4-python (Uvicorn direct, single worker)
# -------------------------------------------------------------------
if command -v uvicorn &>/dev/null; then
    run_benchmark \
        "tina4_uvicorn" \
        "uvicorn app_tina4_hypercorn:app --host 0.0.0.0 --port 8106 --log-level error" \
        8106
else
    echo "--- tina4_uvicorn: SKIPPED (uvicorn not found) ---" | tee -a "$SUMMARY"
    echo "" | tee -a "$SUMMARY"
fi

# -------------------------------------------------------------------
# 3. Flask (Gunicorn, 4 workers)
# -------------------------------------------------------------------
if $PYTHON -c "import flask" 2>/dev/null; then
    if command -v gunicorn &>/dev/null; then
        run_benchmark \
            "flask_gunicorn" \
            "gunicorn -w 4 -b 0.0.0.0:8102 app_flask:app" \
            8102
    else
        # Fallback to dev server
        echo "  (gunicorn not found, using Flask dev server)" | tee -a "$SUMMARY"
        run_benchmark \
            "flask_dev" \
            "$PYTHON app_flask.py" \
            8102
    fi
else
    echo "--- Flask: SKIPPED (not installed, run: pip install flask gunicorn) ---" | tee -a "$SUMMARY"
    echo "" | tee -a "$SUMMARY"
fi

# -------------------------------------------------------------------
# 4. FastAPI (Uvicorn)
# -------------------------------------------------------------------
if $PYTHON -c "import fastapi" 2>/dev/null; then
    if command -v uvicorn &>/dev/null; then
        run_benchmark \
            "fastapi_uvicorn" \
            "uvicorn app_fastapi:app --host 0.0.0.0 --port 8103 --log-level error" \
            8103
    else
        echo "--- FastAPI: SKIPPED (uvicorn not found) ---" | tee -a "$SUMMARY"
        echo "" | tee -a "$SUMMARY"
    fi
else
    echo "--- FastAPI: SKIPPED (not installed, run: pip install fastapi uvicorn) ---" | tee -a "$SUMMARY"
    echo "" | tee -a "$SUMMARY"
fi

# -------------------------------------------------------------------
# 5. Django (Gunicorn, 4 workers)
# -------------------------------------------------------------------
if $PYTHON -c "import django" 2>/dev/null; then
    if command -v gunicorn &>/dev/null; then
        run_benchmark \
            "django_gunicorn" \
            "gunicorn -w 4 -b 0.0.0.0:8104 app_django:application" \
            8104
    else
        echo "  (gunicorn not found, using Django dev server)" | tee -a "$SUMMARY"
        run_benchmark \
            "django_dev" \
            "$PYTHON app_django.py" \
            8104
    fi
else
    echo "--- Django: SKIPPED (not installed, run: pip install django gunicorn) ---" | tee -a "$SUMMARY"
    echo "" | tee -a "$SUMMARY"
fi

echo "============================================" | tee -a "$SUMMARY"
echo " Benchmark complete. Summary: $SUMMARY"       | tee -a "$SUMMARY"
echo "============================================" | tee -a "$SUMMARY"
