# HoneyChain web client — built once, served as static files by nginx.
#
# The API is reached same-origin at /api (proxied to the backend service), so
# the refresh-token cookie works without cross-site settings.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Public, build-time values only (VITE_*). Never put a secret here.
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_APP_NAME=HoneyChain
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_APP_NAME=$VITE_APP_NAME
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
