"""Gallery: Error Overlay — deliberately crash to demo the debug overlay."""
from tina4_python.core.router import get


@get("/api/gallery/crash")
async def gallery_crash(request, response):
    """This route deliberately raises an error to showcase the error overlay.

    In debug mode (TINA4_DEBUG=true), you'll see:
    - Exception type and message
    - Stack trace with syntax-highlighted source code
    - The exact line that caused the error (highlighted)
    - Request details (method, path, headers)
    - Environment info (framework version, Python version)
    """
    # Simulate a realistic error — accessing a missing key
    user = {"name": "Alice", "email": "alice@example.com"}
    role = user["role"]  # KeyError: 'role' — this line will be highlighted in the overlay
    return response({"role": role})
