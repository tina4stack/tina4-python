# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
