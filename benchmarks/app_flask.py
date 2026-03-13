"""Flask benchmark app.

Usage:
    gunicorn -w 4 -b 0.0.0.0:8102 app_flask:app
    or: python app_flask.py  (dev server, not representative)
"""
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/api/hello")
def hello():
    return jsonify(message="Hello, World!")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8102)
