from tina4_python import run_web_server
from tina4_python.Router import get

@get("/health-check")
async def index(request, response):

    return response(f"OK")

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7145)
