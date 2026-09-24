# Copyright (c) 2026 Code Infinity
# SPDX-License-Identifier: MPL-2.0
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Tina4 Store Demo — runs on tina4stack/tina4-python:v3
#
# Build:  docker build -t tina4-store .
# Run:    docker run -p 7145:7145 tina4-store
# Browse: http://localhost:7145

FROM tina4stack/tina4-python:v3
WORKDIR /app

# Copy application code
COPY app.py .
COPY .env .
COPY migrations/ migrations/
COPY src/ src/

# Data directory for SQLite + sessions
RUN mkdir -p data data/sessions data/queue data/mailbox

EXPOSE 7146
CMD ["python", "app.py"]
