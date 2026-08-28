# syntax=docker/dockerfile:1

FROM node:24-alpine AS build

ENV NEXT_TELEMETRY_DISABLED=1
ARG MOSAIC_API_ORIGIN=http://api:8000
ARG MOSAIC_BUILD_REVISION=local
ENV MOSAIC_API_ORIGIN=${MOSAIC_API_ORIGIN}
WORKDIR /app

RUN npm install --global pnpm@11.19.0

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/design-tokens/package.json packages/design-tokens/package.json
RUN pnpm install --frozen-lockfile

COPY apps/web apps/web
COPY packages packages
RUN pnpm --filter @mosaic/web build

FROM node:24-alpine AS runtime

ARG MOSAIC_BUILD_REVISION=local
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
ENV NODE_OPTIONS=--no-experimental-require-module
ENV HOME=/home/mosaic
WORKDIR /app

LABEL org.opencontainers.image.revision=${MOSAIC_BUILD_REVISION}

RUN addgroup --system --gid 10001 mosaic \
    && adduser --system --uid 10001 --ingroup mosaic mosaic

COPY --from=build --chown=mosaic:mosaic /app/apps/web/.next/standalone ./
COPY --from=build --chown=mosaic:mosaic /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=mosaic:mosaic /app/apps/web/public ./apps/web/public

USER mosaic
EXPOSE 3000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"
CMD ["node", "apps/web/server.js"]
