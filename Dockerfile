# docker.io/tina4stack/tina4-python
# Base image for Tina4 Python apps
#
# Usage in your project. THREE STEPS, in this order: inherit, bring in a package
# manager, then modify. That shape is the same for all four Tina4 base images.
#
#   FROM docker.io/tina4stack/tina4-python:3.13.92
#   COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv   # 2. package manager
#   RUN uv pip install --system psycopg2-binary                     # 3. modify
#   COPY . .
#
# WHY uv AND NOT pip. There is no working pip in this image, and that is not an
# oversight you should route around: the runtime strips most of the standard
# library (see the prune below), which leaves pip itself broken. `pip` is not on
# PATH, and `python -m pip install` finds the module and then fails. uv is a
# single static binary that carries what it needs, so it works where pip cannot.
#
# uv is NOT baked in, deliberately. The binary is 50.8 MB against a 41 MB image:
# shipping it would more than double the leanest base image we publish, for
# something most deployments never invoke. Copying it in costs the base nothing
# and costs you one line. Verified: the two lines above install redis 8.0.1
# alongside tina4_python 3.13.92 in a 95 MB derived image.
#
# The default database is SQLite, built into Python with no dependency at all,
# so a plain `FROM` plus your code needs no package manager whatsoever.
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

# Strip unused stdlib and caches.
#
# DO NOT prune dist-info from /install/lib. That line used to be here and it cost
# the framework its version: __init__.py resolves __version__ from pyproject.toml
# (absent in an installed package), then importlib.metadata.version(), then a
# floor literal. Deleting the dist-info directory removes the ONLY metadata the
# second path can read, so importlib raised PackageNotFoundError and every image
# fell through to the literal -- the published tina4-python:3.13.92 served
# "version": "3.13.56" on /health, 36 releases stale.
#
# It bought nothing. tina4-python has zero runtime dependencies, so /install/lib
# holds one package and one dist-info: about 20 KB of an image that measures 41 MB
# on amd64. Trading correct version reporting for 0.05% of the image is a bad deal.
RUN set -e; \
    find /usr/local/lib/python3.13 /install/lib -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
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
