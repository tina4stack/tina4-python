# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Roles
ROLE_CUSTOMER = "customer"
ROLE_ADMIN = "admin"

# Order statuses
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_SHIPPED = "shipped"
STATUS_DELIVERED = "delivered"
STATUS_CANCELLED = "cancelled"

ORDER_STATUSES = [STATUS_PENDING, STATUS_PROCESSING, STATUS_SHIPPED, STATUS_DELIVERED, STATUS_CANCELLED]

# Limits
PRODUCTS_PER_PAGE = 12
ORDERS_PER_PAGE = 20
LOW_STOCK_THRESHOLD = 5
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"]
