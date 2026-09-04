# Build context MUST be the monorepo root (not this directory):
#   docker build -f apps/web-candidate/Dockerfile -t aiva-web-candidate .
#
# Not wired into compose.yaml: local dev uses `pnpm --filter @aiva/web-candidate
# dev` directly. This Dockerfile is for the Helm chart / any container-based
# deployment target -- verified via docker build + docker run + a real HTTP
# request in this repo's own history (docs/DECISIONS.md's ADR-030).
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
COPY apps/web-candidate ./apps/web-candidate
RUN pnpm --filter @aiva/web-candidate run build

FROM nginx:1.27-alpine AS runtime
ENV AIVA_API_UPSTREAM=http://api:8000
COPY apps/web-candidate/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /repo/apps/web-candidate/dist /usr/share/nginx/html
EXPOSE 80
