# ---------------------------------------------------------------------------
# MicroSeg frontend — build the Vue SPA, serve the static bundle with nginx,
# and proxy /api (incl. the task WebSocket) to the api service.
#
# Build context is the REPOSITORY ROOT (see docker-compose.yml) so the build
# can read both ./frontend and the shared ./deploy/nginx config.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
