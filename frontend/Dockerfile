# Static-asset container for the local docker-compose setup. Built from the
# repo root as context (it needs deploy/nginx.conf), so paths below are
# repo-relative — see docker-compose.yml.
#
# The deployed single-image build does NOT use this file; there FastAPI serves
# the same dist/ directly. See the repo-root Dockerfile.

FROM node:20-alpine AS build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:alpine

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /frontend/dist /usr/share/nginx/html

EXPOSE 80
