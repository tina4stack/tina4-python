from tina4_python import run_web_server
from tina4_python.Router import get


@get("/")
async def get_hello_world(request, response):
    return response("Hello World!")


def app():
    run_web_server()


if __name__ == "__main__":
    app()
