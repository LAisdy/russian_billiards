# pyramid-web frontend — static Three.js app served by nginx, which also
# reverse-proxies /api and /ws to the backend service (see nginx.conf).
# Build context: pyramid-web/ (project root), so paths are relative to it.

FROM nginx:1.27-alpine

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/ /usr/share/nginx/html

EXPOSE 80
