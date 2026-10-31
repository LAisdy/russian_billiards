# pyramid-web frontend — static Three.js app served by nginx, which also
# reverse-proxies /api and /ws to the backend service (see nginx.conf).
# MULTI-STAGE build:
#
#   stage 1 (build)   — node runs `node --check` on every first-party JS
#                       module: a syntax error anywhere fails the image
#                       build BEFORE it can be shipped (no bundler here —
#                       the ES modules are vendored and served as-is, so a
#                       parse gate is the whole "build")
#   stage 2 (runtime) — nginx:1.27-alpine serves the validated files
#
# Build context: pyramid-web/ (project root), so paths are relative to it:
#     docker build -f docker/frontend.Dockerfile .
# (docker-compose.yml already wires this up: `docker compose up -d --build`)

# --- stage 1: syntax gate -----------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /src
COPY frontend/ /src/frontend/

# Same check the local verify suite runs (scripts/verify_step8_ui.py):
# main.js, lobby.js and ui_math.js must all parse. Node 22 auto-detects ES
# modules, matching how the browser consumes them.
RUN node --check frontend/main.js \
    && node --check frontend/lobby.js \
    && node --check frontend/ui_math.js

# --- stage 2: runtime ---------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/frontend/ /usr/share/nginx/html

EXPOSE 80
