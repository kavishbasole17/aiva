# Build context MUST be the monorepo root (not this directory) -- this app
# depends on the packages/ui workspace package, so pnpm needs the whole
# workspace, not just apps/web-recruiter in isolation:
#   docker build -f apps/web-recruiter/Dockerfile -t aiva-web-recruiter .
#
# Not wired into compose.yaml: local dev uses `pnpm --filter @aiva/web-recruiter
# dev` directly (Vite's own dev server + HMR), which this production build
# doesn't replace. This Dockerfile exists for the Helm chart / any
# container-based deployment target, verified via `docker build` +
# `docker run` + a real HTTP request in this repo's own history (see
# docs/DECISIONS.md's ADR-030), not left untested.
FROM node:22-slim AS builder
WORKDIR /repo

RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

COPY pnpm-workspace.yaml pnpm-lock.yaml package.json ./
COPY packages/ui/package.json packages/ui/package.json
COPY packages/contracts/package.json packages/contracts/package.json
COPY apps/web-recruiter/package.json apps/web-recruiter/package.json
COPY apps/web-candidate/package.json apps/web-candidate/package.json
RUN pnpm install --frozen-lockfile

COPY packages ./packages
COPY apps/web-recruiter ./apps/web-recruiter
RUN pnpm --filter @aiva/web-recruiter run build

FROM nginx:1.27-alpine AS runtime
# nginx's own entrypoint runs envsubst over templates/*.template into
# conf.d/*.conf at container startup, restricted to names that are actually
# set as real env vars -- nginx's own $host/$remote_addr/etc. survive
# untouched since they aren't env vars, only ${AIVA_API_UPSTREAM} is.
ENV AIVA_API_UPSTREAM=http://api:8000
COPY apps/web-recruiter/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /repo/apps/web-recruiter/dist /usr/share/nginx/html
EXPOSE 80
