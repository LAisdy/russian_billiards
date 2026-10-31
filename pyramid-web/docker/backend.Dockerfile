# pyramid-web backend — FastAPI service wrapping the vendored pooltool
# physics engine. MULTI-STAGE build:
#
#   stage 1 (builder) — install the pinned dependency stack into a clean
#                       virtualenv at /opt/venv
#   stage 2 (runtime) — same slim base, only the venv + application code,
#                       non-root user, no pip, no build tools
#
# Build context: pyramid-web/ (project root), so paths are relative to it:
#     docker build -f docker/backend.Dockerfile .
# (docker-compose.yml already wires this up: `docker compose up -d --build`)

# --- stage 1: builder ---------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The pinned stack (numpy/numba/llvmlite/scipy) ships manylinux wheels for
# cp312, so no compiler toolchain is needed here — pip just unpacks wheels.
WORKDIR /build
COPY backend/requirements.txt ./requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# --- stage 2: runtime ---------------------------------------------------------
FROM python:3.12-slim AS runtime

# PYTHONHASHSEED=0: layouts.py assigns rack ball IDs via
# random.choice(list(<set of str>)); a fixed hash seed makes seeded racks
# reproducible across processes/restarts (see app/physics.py docstring).
# PYTHONDONTWRITEBYTECODE=1 keeps the image layers clean of stray .pyc;
# numba's own .nbc JIT cache (decision #14) still persists in __pycache__.
# PYRAMID_STATIC_DIR: app/main.py serves this frontend copy at "/" (gzip on),
# so ONE container exposes UI + REST + WS on one origin — the single-service
# deployment shape used on render.com. docker-compose keeps nginx in front
# (its copy is authoritative there); serving the tree twice is harmless.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    PYRAMID_STATIC_DIR=/app/static \
    PATH="/opt/venv/bin:$PATH"

# libgomp1: numba's default (OpenMP) threading layer dlopens libgomp at
# runtime; the slim base image does not ship it. Without it numba silently
# falls back to the slow workqueue layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

# Virtualenv with the full dependency stack from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Application code + the vendored pooltool physics package (byte-identical
# copy of the source repo — provenance and diff policy in
# backend/pooltool/VENDORED.md). Importable as top-level `pooltool` because
# WORKDIR /app is on sys.path (uvicorn's --app-dir default).
COPY backend/app ./app
COPY backend/pooltool ./pooltool
COPY frontend ./static

# Non-root runtime; /app is chowned so numba's JIT disk cache (written next
# to the vendored sources) survives container restarts instead of silently
# disabling itself on a read-only path.
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# --reload is intentionally off: this is the production container. The app
# must run as a SINGLE worker process (in-memory lobby state + numba cache).
#
# Shell-form CMD so the port is configurable at run time:
#   - render.com injects PORT (default 10000) and requires the service to
#     bind to it — this is what makes the deploy routable;
#   - docker-compose sets no PORT, so the default 8000 applies there and the
#     compose healthcheck (http://localhost:8000/api/health) is unchanged.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
