# pyramid-web backend — FastAPI service.
# Build context: pyramid-web/ (project root), so paths are relative to it.

FROM python:3.12-slim

# PYTHONHASHSEED=0: layouts.py assigns rack ball IDs via
# random.choice(list(<set of str>)); a fixed hash seed makes seeded racks
# reproducible across processes/restarts (see app/physics.py docstring).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONHASHSEED=0

# libgomp1: numba's default (OpenMP) threading layer dlopens libgomp at
# runtime; the slim base image does not ship it. Without it numba silently
# falls back to the slow workqueue layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first for layer caching.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code + the vendored pooltool physics package (byte-identical
# copy of the source repo — provenance and diff policy in
# backend/pooltool/VENDORED.md). Importable as top-level `pooltool` because
# WORKDIR /app is on sys.path (uvicorn's --app-dir default).
COPY backend/app ./app
COPY backend/pooltool ./pooltool

EXPOSE 8000

# --reload is intentionally off: this is the production container. The app
# must run as a SINGLE worker process (in-memory lobby state + numba cache).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
