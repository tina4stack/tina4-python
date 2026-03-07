import os, tina4_python
from tina4_python import Debug
from tina4_python import run_web_server
from tina4_python.Router import get

@get("/health-check")
async def get_healthcheck(request, response):
    if os.path.isfile(tina4_python.root_path + "/broken"):
        Debug.error("broken", tina4_python.root_path + "/broken")
        return response("Broken", 503)
    return response("OK")

if __name__ == "__main__":
    run_web_server("0.0.0.0", 7148)
