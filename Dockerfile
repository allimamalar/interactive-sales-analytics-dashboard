# =============================================================================
# Dockerfile — Interactive Sales Analytics Dashboard
# =============================================================================
# Base image  : python:3.11-slim   (Debian Bookworm slim variant)
# Exposed port: 8501  (default Streamlit port)
# Health check: polls /healthz every 30 s
# Entrypoint  : python app.py  (Streamlit auto-detects the script)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Base image
#   python:3.11-slim gives us a minimal Debian + CPython 3.11 runtime without
#   the full standard-library test suites or development headers, keeping the
#   final image compact while still allowing C-extension builds via apt-get.
# -----------------------------------------------------------------------------
FROM python:3.11-slim

# =============================================================================
# Environment Variables
# =============================================================================

# Prevent Python from writing .pyc bytecode files into the container image.
# This reduces image size and avoids stale cache confusion on hot-reloads.
ENV PYTHONDONTWRITEBYTECODE=1

# Force Python's stdout / stderr to be unbuffered so that log lines emitted
# by Streamlit and our own print() calls appear immediately in `docker logs`.
ENV PYTHONUNBUFFERED=1

# Tell pip not to use the cache directory so the layer stays lean.
ENV PIP_NO_CACHE_DIR=1

# Suppress the pip version-check nag that pollutes build output.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# =============================================================================
# System Dependencies
# =============================================================================
# Install the minimal OS-level libraries required by the Python packages:
#   - libgomp1        : OpenMP runtime used by NumPy / SciPy BLAS back-ends.
#   - libatlas-base-dev is intentionally omitted from slim; OpenBLAS ships
#     inside the numpy wheel, so no extra BLAS lib is needed.
#   - gcc / build-essential: required only if pip needs to compile C extensions
#     from source (the pre-built wheels for numpy / pandas cover most platforms,
#     but having gcc prevents silent failures on edge-case architectures).
#   - curl             : used by the HEALTHCHECK probe below.
#
# We chain all apt commands in a single RUN layer and clean up afterwards to
# keep the layer count and image size minimal.
# =============================================================================
RUN apt-get update --quiet \
    && apt-get install --yes --no-install-recommends \
        # C runtime for native extensions (numpy, pandas Cython modules, etc.)
        gcc \
        # OpenMP shared library — required by NumPy's multiprocessing paths.
        libgomp1 \
        # curl is used by the HEALTHCHECK instruction below.
        curl \
    # Remove downloaded package lists — they are not needed at runtime.
    && rm -rf /var/lib/apt/lists/* \
    # Purge the apt cache to shrink the layer further.
    && apt-get clean

# =============================================================================
# Working Directory
# =============================================================================
# Create and switch to /app as the container's working directory.
# All subsequent COPY and RUN instructions operate relative to this path.
# =============================================================================
WORKDIR /app

# =============================================================================
# Python Dependencies
# =============================================================================
# Copy the requirements file first (before app source) so Docker's layer cache
# can reuse the pip-install layer on subsequent builds when only app.py changes.
# =============================================================================
COPY . .
# Install all Python packages in a single pip call.
#   --no-cache-dir  : already set via ENV but specified here for clarity.
#   --upgrade       : ensure pip itself is up-to-date before resolving deps.
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Application Source
# =============================================================================
# Copy the dashboard source code into the working directory.
# This layer is intentionally placed after the pip-install layer so that
# editing app.py does not invalidate the (expensive) dependency layer.
# =============================================================================
COPY app.py .

# =============================================================================
# Non-Root User (Security Hardening)
# =============================================================================
# Running as root inside a container is a security anti-pattern.
# We create a dedicated system user 'appuser' and switch to it for runtime.
# =============================================================================
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

# =============================================================================
# Port Exposure
# =============================================================================
# Declare that the container listens on port 8501 at runtime.
# This is metadata for `docker run -p` and container orchestrators; it does
# not publish the port by itself.
# =============================================================================
EXPOSE 8501

# =============================================================================
# Health Check
# =============================================================================
# Docker will call this command every 30 seconds to determine container health.
# Streamlit exposes a lightweight health endpoint at /healthz (>= 1.28) that
# returns HTTP 200 when the server is ready to accept connections.
#
#   --interval=30s  : probe every 30 seconds.
#   --timeout=10s   : mark unhealthy if the probe does not respond in 10 s.
#   --start-period=15s : grace period for the app to initialise before the
#                        first probe counts against the failure threshold.
#   --retries=3     : declare the container unhealthy after 3 consecutive
#                     failures.
# =============================================================================
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=15s \
    --retries=3 \
    CMD curl --fail --silent http://localhost:8501/healthz || exit 1

# =============================================================================
# Entrypoint / Command
# =============================================================================
# We use ENTRYPOINT + CMD (the "exec form") so the process runs as PID 1,
# which ensures SIGTERM is delivered directly to the Python process and
# allows graceful shutdown without a shell wrapper.
#
# Streamlit flags:
#   --server.port=8501         : explicit port (matches EXPOSE above).
#   --server.address=0.0.0.0   : bind on all interfaces so the port is
#                                 reachable from outside the container.
#   --server.headless=true     : disable the browser-open prompt and the
#                                 email-collection dialog (CI / server mode).
#   --server.enableCORS=false  : allow iframe embedding in orchestrator UIs.
#   --server.enableXsrfProtection=false : simplify reverse-proxy setups.
# =============================================================================
ENTRYPOINT ["python", "-m", "streamlit", "run", "app.py"]
CMD [ \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--server.headless=true", \
    "--server.enableCORS=false", \
    "--server.enableXsrfProtection=false" \
]
