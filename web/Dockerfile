FROM node:22-alpine AS base
# Optional resolver override for networks where the build's default DNS is flaky.
# Applies to RUN steps only; nothing is persisted in the image.
ARG BUILD_DNS=""
# Keep the pnpm store inside node_modules so it is copied into the
# node_modules named volume and startup installs can stay offline.
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN if [ -n "$BUILD_DNS" ]; then echo "nameserver $BUILD_DNS" > /etc/resolv.conf; fi \
    && npm install --global pnpm@12.18.0 \
    && pnpm install --frozen-lockfile --store-dir /app/node_modules/.pnpm-store


FROM base AS dev
COPY . .
CMD ["pnpm", "dev"]


FROM base AS build
COPY . .
RUN pnpm build
