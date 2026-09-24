# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import uuid
from tina4_python.core.router import post, noauth, middleware
from src.middleware.admin_auth import AdminAuth

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../public/uploads")
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/svg+xml"}


# @noauth bypasses built-in Bearer check — AdminAuth validates via session token instead
@noauth()
@middleware(AdminAuth)
@post("/api/upload/product-image")
async def upload_product_image(request, response):
    file = request.files.get("image")
    if not file:
        return response({"error": "No file provided"}, 400)

    if file.get("type") not in ALLOWED_TYPES:
        return response({"error": f"Invalid file type: {file.get('type')}"}, 400)

    original = file.get("filename", "image.jpg")
    ext = original.rsplit(".", 1)[-1] if "." in original else "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(file["content"])

    return response({"url": f"/uploads/{filename}", "filename": filename})
