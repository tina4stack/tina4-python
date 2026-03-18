import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import threading
import tina4_python
from tina4_python import run_web_server
from tina4_python.Database import Database
from tina4_python.ORM import ORM, orm
from tina4_python.Migration import migrate
from tina4_python.Queue import Queue, Consumer

# Database setup
db = Database("sqlite3:app.db")
orm(db)
migrate(db)

# Start the job consumer in a background thread
from src.app.processor import process_job

queue = Queue(topic="jobs", callback=process_job)
consumer = Consumer(queue)
consumer_thread = threading.Thread(target=consumer.run_forever, daemon=True)
consumer_thread.start()

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7149)
