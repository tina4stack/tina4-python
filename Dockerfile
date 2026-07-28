# docker.io/tina4stack/tina4-python
# Base image for Tina4 Python apps
#
# Usage in your project:
#   FROM docker.io/tina4stack/tina4-python:3.13.92
#   COPY . .
#   CMD ["python", "app.py"]
#
# Build:
#   docker build -t docker.io/tina4stack/tina4-python:3.13.92 .
#   docker push docker.io/tina4stack/tina4-python:3.13.92

FROM python:3.13-alpine3.23 AS builder
RUN apk add --no-cache build-base libffi-dev
WORKDIR /build
COPY pyproject.toml README.md ./
COPY tina4_python/ tina4_python/
RUN pip install --no-cache-dir --prefix=/install .

# Strip unused stdlib, caches, dist-info
RUN set -e; \
    find /usr/local/lib/python3.13 /install/lib -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
    find /install/lib -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null; \
    rm -rf /usr/local/lib/python3.13/test \
           /usr/local/lib/python3.13/tkinter \
           /usr/local/lib/python3.13/idlelib \
           /usr/local/lib/python3.13/turtledemo \
           /usr/local/lib/python3.13/ensurepip \
           /usr/local/lib/python3.13/lib2to3 \
           /usr/local/lib/python3.13/pydoc_data \
           /usr/local/lib/python3.13/pydoc.py \
           /usr/local/lib/python3.13/turtle.py \
           /usr/local/lib/python3.13/doctest.py \
           /usr/local/lib/python3.13/xmlrpc \
           /usr/local/lib/python3.13/curses \
           /usr/local/lib/python3.13/dbm \
           /usr/local/lib/python3.13/venv \
           /usr/local/lib/python3.13/distutils \
           /usr/local/lib/python3.13/ctypes \
           /usr/local/lib/python3.13/unittest \
           /usr/local/lib/python3.13/_pyrepl \
           /usr/local/lib/python3.13/wsgiref \
           /usr/local/lib/python3.13/config-* \
    ; \
    cd /usr/local/lib/python3.13/lib-dynload && \
    rm -f _tkinter* _curses* _dbm* _lzma* _bz2* \
          _test* audioop* nis* ossaudio* \
          _ctypes_test* _xxtestfuzz* \
          _multiprocessing* _xxsubinterpreters* _xxinterpchannels* \
    ; \
    strip /usr/local/bin/python3.13 2>/dev/null; \
    strip /usr/local/lib/libpython3.13.so.1.0 2>/dev/null; \
    true

# ── Runtime ───────────────────────────────────────────────────
FROM alpine:3.23
WORKDIR /app

# SQLite only — add database drivers in your Dockerfile (see DEPLOYING.md)
RUN apk add --no-cache libffi sqlite-libs

COPY --from=builder /usr/local/bin/python3.13 /usr/local/bin/python
COPY --from=builder /usr/local/lib/libpython3.13.so.1.0 /usr/local/lib/
COPY --from=builder /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=builder /install/lib /usr/local/lib

RUN ln -s /usr/local/bin/python /usr/local/bin/python3 && \
    ln -s /usr/local/lib/libpython3.13.so.1.0 /usr/local/lib/libpython3.13.so && \
    ldconfig /usr/local/lib 2>/dev/null || true

## Copy bundled demo app (runs out of the box)
COPY example/ /app/

EXPOSE 7146
ENV PYTHONUNBUFFERED=1
ENV TINA4_OVERRIDE_CLIENT=true
ENV TINA4_DEBUG=false
ENV HOST=0.0.0.0
ENV PORT=7146
ENV TINA4_NO_BROWSER=true
CMD ["python", "app.py"]
