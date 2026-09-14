# stock-analyst/Dockerfile
FROM python:3.11-slim@sha256:9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7 AS runtime

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DATA_PATH=/data

# Set working directory
WORKDIR /app

# Copy and install Python dependencies first (for better Docker caching)
COPY requirements.txt requirements.lock ./
# Compile/install dependencies, then remove the toolchain from the runtime
# filesystem.  Runtime code consumes the installed manylinux wheels and must
# not retain Git or compilers merely because they were needed at build time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ git libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev libpng-dev \
    && python -m pip install --no-cache-dir -r requirements.lock \
    && apt-get purge -y --auto-remove \
        gcc g++ git libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY src/ src/
COPY prompts/ prompts/
COPY main.py .

# Create data directory for outputs
RUN mkdir -p /data

# Use a shared volume for outputs
VOLUME ["/data"]

FROM runtime AS test
COPY requirements-test.lock ./
RUN python -m pip install --no-cache-dir -r requirements-test.lock
COPY Dockerfile ./Dockerfile
COPY tests/ tests/
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]

FROM runtime AS production
ARG VYNN_SOURCE_REVISION=unversioned
LABEL org.opencontainers.image.revision=$VYNN_SOURCE_REVISION
ENV VYNN_SOURCE_REVISION=$VYNN_SOURCE_REVISION
# Set the entry point
ENTRYPOINT ["python", "main.py"]
