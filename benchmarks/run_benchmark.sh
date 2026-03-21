#!/bin/bash
# Tina4 v3 — Reproducible HTTP Benchmark
# Usage: ./run_benchmark.sh [--runs N] [--requests N] [--concurrency N]
#
# Prerequisites: hey, ab, curl
# All frameworks must be running on their ports before execution.

set -euo pipefail

RUNS=${1:-5}
REQUESTS=5000
CONCURRENCY=50
WARMUP_REQUESTS=500

echo "================================================================"
echo "  Tina4 v3 — Reproducible HTTP Benchmark"
echo "================================================================"
echo ""
echo "  Date:        $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "  Machine:     $(uname -m) $(uname -s)"
echo "  CPU:         $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'unknown')"
echo "  Memory:      $(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f GB", $1/1024/1024/1024}' || echo 'unknown')"
echo "  hey version: $(hey -version 2>&1 || echo 'unknown')"
echo "  ab version:  $(ab -V 2>&1 | head -1 || echo 'unknown')"
echo ""
echo "  Config:      $REQUESTS requests, $CONCURRENCY concurrent, $RUNS runs (median reported)"
echo "  Warm-up:     $WARMUP_REQUESTS requests discarded before each test"
echo ""

# Framework ports
declare -A FRAMEWORKS=(
  ["Tina4 Python"]=7145
  ["Tina4 PHP"]=7146
  ["Tina4 Ruby"]=7147
  ["Tina4 Node.js"]=7148
  ["Flask"]=7200
  ["Starlette"]=7201
  ["FastAPI"]=7202
  ["Node.js raw"]=7203
  ["Express"]=7204
  ["Fastify"]=7205
  ["Sinatra"]=7206
  ["Bottle"]=7207
)

# Detect which are running
echo "  Detecting running frameworks..."
ACTIVE=()
for name in "${!FRAMEWORKS[@]}"; do
  port=${FRAMEWORKS[$name]}
  if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${port}/api/bench/json" 2>/dev/null | grep -q "200"; then
    ACTIVE+=("$name")
    body=$(curl -s "http://127.0.0.1:${port}/api/bench/json")
    echo "    ✅ $name (:$port) — $body"
  fi
done

if [ ${#ACTIVE[@]} -eq 0 ]; then
  echo "    ❌ No frameworks detected. Start servers first."
  exit 1
fi

echo ""
echo "  Running benchmarks (${#ACTIVE[@]} frameworks × 2 endpoints × $RUNS runs)..."
echo ""

# Results arrays
declare -A JSON_RESULTS
declare -A LIST_RESULTS

for name in "${ACTIVE[@]}"; do
  port=${FRAMEWORKS[$name]}

  # Warm up
  hey -n $WARMUP_REQUESTS -c 10 "http://127.0.0.1:${port}/api/bench/json" > /dev/null 2>&1

  # JSON endpoint — N runs
  json_values=()
  for ((r=1; r<=RUNS; r++)); do
    rps=$(hey -n $REQUESTS -c $CONCURRENCY "http://127.0.0.1:${port}/api/bench/json" 2>&1 | grep "Requests/sec" | awk '{printf "%.0f", $2}')
    json_values+=($rps)
  done

  # Sort and take median
  IFS=$'\n' sorted=($(sort -n <<<"${json_values[*]}")); unset IFS
  median_idx=$(( RUNS / 2 ))
  JSON_RESULTS[$name]=${sorted[$median_idx]}

  # Warm up list
  hey -n $WARMUP_REQUESTS -c 10 "http://127.0.0.1:${port}/api/bench/list" > /dev/null 2>&1

  # List endpoint — N runs
  list_values=()
  for ((r=1; r<=RUNS; r++)); do
    rps=$(hey -n $REQUESTS -c $CONCURRENCY "http://127.0.0.1:${port}/api/bench/list" 2>&1 | grep "Requests/sec" | awk '{printf "%.0f", $2}')
    list_values+=($rps)
  done

  IFS=$'\n' sorted=($(sort -n <<<"${list_values[*]}")); unset IFS
  LIST_RESULTS[$name]=${sorted[$median_idx]}

  printf "    %-22s JSON: %6s req/s (median of %s runs: %s)  List: %6s req/s\n" \
    "$name" "${JSON_RESULTS[$name]}" "$RUNS" "$(IFS=,; echo "${json_values[*]}")" "${LIST_RESULTS[$name]}"
done

echo ""
echo "================================================================"
echo "  RESULTS (median of $RUNS runs)"
echo "================================================================"
echo ""
printf "  %-22s %12s  |  %12s\n" "Framework" "JSON req/s" "List req/s"
echo "  ────────────────────────────────────────────────────────────"

# Sort by JSON performance
for name in $(for k in "${!JSON_RESULTS[@]}"; do echo "${JSON_RESULTS[$k]} $k"; done | sort -rn | awk '{$1=""; print substr($0,2)}'); do
  printf "  %-22s %12s  |  %12s\n" "$name" "${JSON_RESULTS[$name]}" "${LIST_RESULTS[$name]}"
done

echo ""
echo "  Methodology: $RUNS runs per endpoint, $WARMUP_REQUESTS warm-up requests discarded,"
echo "  $REQUESTS requests at $CONCURRENCY concurrency per run, median reported."
echo "  Tool: hey (https://github.com/rakyll/hey)"
echo ""
