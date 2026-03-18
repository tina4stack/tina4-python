# Job Queue Example

Background job processing with a dashboard.

## Features
- Queue producer/consumer with litequeue (SQLite-backed)
- Background thread processes jobs asynchronously
- Three job types: fetch weather, send notification, generate report
- ORM-tracked job status (pending, processing, completed, failed)
- Auto-refreshing dashboard
- Uses tina4helper.js for AJAX requests

## Run
```bash
cd examples/job-queue
python app.py
# Open http://localhost:7149
# Click buttons to enqueue jobs, watch them process in real-time
```
