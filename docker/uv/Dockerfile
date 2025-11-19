# === Build Stage ===
FROM python:3.13-alpine AS builder

# Install build dependencies
RUN apk add --no-cache \
    build-base \
    libffi-dev \
    python3-dev \
    py3-pip \
    cargo

# Install UV
# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin/:$PATH"

WORKDIR /app

# Copy only dependency files to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

RUN /root/.local/bin/uv pip install --system -e .

# Copy app source
COPY . .

# === Final Stage ===
FROM python:3.13-alpine

# Install only runtime libraries
RUN apk add --no-cache \
    libffi \
    libstdc++ \
    libgcc \
    python3

WORKDIR /app

# Copy installed site-packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy app source code
COPY --from=builder /app /app

# Expose port
EXPOSE 8080

ENV SWAGGER_TITLE="Swagger"
ENV SWAGGER_VERSION="0.0.1"
ENV SWAGGER_DESCRIPTION="Swagger documentation"

# Set entrypoint
CMD ["python3", "app.py", "0.0.0.0:8080", "-u"]
