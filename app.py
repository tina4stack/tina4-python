from tina4_python import run_web_server
from tina4_python.Router import get

@get("/")
async def index(request, response):
    return response(f"Hello Tina4!")

if __name__ == "__main__":
    run_web_server()
