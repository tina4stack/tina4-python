"""FastAPI benchmark app.

Usage:
    uvicorn app_fastapi:app --host 0.0.0.0 --port 8103
"""
from fastapi import FastAPI

app = FastAPI()

@app.get("/api/hello")
async def hello():
    return {"message": "Hello, World!"}
