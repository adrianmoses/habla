# syntax=docker/dockerfile:1
#
# Builds the hable-ya SPA and bakes it into a Caddy image that serves it at /srv
# (spec #018). Published to GHCR by release.yml as `<repo>-web`; the prod overlay
# (docker-compose.prod.yml) runs this image as the `caddy` service, mounting the
# repo Caddyfile over the default one.
#
# NO build args / NO token: per OQ1 Option B the session-auth token is pasted by
# the operator at runtime and kept in the browser's sessionStorage — nothing
# secret is ever baked into the bundle or this image.

########## Build stage ##########
FROM node:20-alpine AS build

WORKDIR /app

# Dependency layer — cached until the lockfile changes. `npm ci` installs
# devDependencies too (tsc/vite live there and `npm run build` needs them).
COPY package.json package-lock.json ./
RUN npm ci

# Source + build. `npm run build` = `tsc --noEmit && vite build` → dist/.
COPY . .
RUN npm run build

########## Runtime stage ##########
FROM caddy:2

# The compiled SPA. The Caddyfile (mounted by the compose overlay) points
# `root * /srv` here; hashed assets + /pcm-worklet.js are served from it.
COPY --from=build /app/dist /srv
