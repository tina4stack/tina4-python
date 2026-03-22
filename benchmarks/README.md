# Tina4 v3 — Benchmark Suite

Cross-language HTTP benchmark suite for Tina4 and competitor frameworks.

## What Each Script Does

| Script | Purpose |
|--------|---------|
| `benchmark.py` | Main benchmark runner — starts framework servers, runs `hey` HTTP benchmarks, collects results into JSON |
| `carbon_benchmarks.py` | Measures CO2 emissions from test suite execution (energy, CPU time, memory) |
| `bench_frond_cache.py` | Template engine (Frond) render benchmarks — measures pre-compilation speedup |
| `compare_frameworks.py` | Generates feature comparison matrices from benchmark result JSON files |

## How to Run

### Full suite (all 4 languages)

```bash
python benchmark.py --all
```

### Single language

```bash
python benchmark.py --python
python benchmark.py --php
python benchmark.py --ruby
python benchmark.py --nodejs
```

### Carbon benchmarks

```bash
python carbon_benchmarks.py
```

### Template benchmarks

```bash
python bench_frond_cache.py
```

## Prerequisites

| Language | Requirements |
|----------|-------------|
| **All** | `hey` HTTP benchmarking tool (`brew install hey` or `go install github.com/rakyll/hey@latest`) |
| **Python** | Python 3.12+, `uv sync` in tina4-python root |
| **PHP** | PHP 8.2+, `composer install` in tina4-php root |
| **Ruby** | Ruby 3.1+, `bundle install` in tina4-ruby root |
| **Node.js** | Node.js 20+, `npm install` in tina4-nodejs root |

## Results

Benchmark results are written as JSON to the `results/` folder:

```
results/
  python.json
  php.json
  ruby.json
  nodejs.json
```

Each JSON file contains:
- **date** — ISO timestamp of the run
- **machine** — architecture and OS
- **config** — number of runs, requests, concurrency, warmup
- **results** — array of framework results with median req/s for JSON and list endpoints

## How to Interpret Results

- **JSON req/s** — throughput for a minimal `{"message": "hello"}` response. Tests raw routing + serialization speed.
- **100-item list req/s** — throughput for a JSON array of 100 objects. Tests serialization of larger payloads.
- **Median** — the middle value of 3 runs. More stable than averages, less affected by outliers.
- **Warmup** — 500 requests sent before measurement to let JIT/caches settle.
- **Deps** — number of third-party dependencies required by the framework.

All frameworks serve identical endpoints on localhost. The benchmarks measure development server performance, not production deployments.

## Consolidated Reports

Each Tina4 repo contains a self-contained `BENCHMARK.md` at its root with performance, features, size, and CO2 data for that language's competitors only.

---

*https://tina4.com*
