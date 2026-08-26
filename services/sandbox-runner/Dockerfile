FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

FROM base AS builder

ARG PIP_INDEX_URL=
COPY pyproject.toml ./
COPY app ./app
RUN pip install ${PIP_INDEX_URL:+--index-url=${PIP_INDEX_URL}} --prefix=/install .

FROM base AS runtime

# nodejs: second execution runtime. util-linux: guarantees `unshare` is
# present (it already ships in the slim base as an essential package, but
# this makes the dependency explicit rather than implicit).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Two kinds of account, deliberately: `aiva` is unused by this service
# (kept only for parity with the other images); `sandbox0`..`sandbox31` is
# what candidate code actually runs as — one dedicated uid per concurrent
# execution slot (app/settings.py's sandbox_uid_pool_*), never shared,
# because a shared uid would let one run read/kill another's via matching
# filesystem/proc ownership (ADR-020). The service process itself stays
# root — see ADR-019 — specifically so it can setuid-drop into one of these
# per execution, which is what keeps RLIMIT_NPROC and any escape scoped
# away from the server's own process. This is the standard "privileged
# supervisor, unprivileged per-job account" shape used by code-execution
# sandboxes (e.g. Judge0), not an oversight — do not add
# `USER aiva`/`USER sandbox0` here. Uids are pinned sequentially from 6666
# rather than left to useradd's auto-assignment, because
# app/settings.py's sandbox_uid_pool_start default has to name the range
# before the container exists.
RUN groupadd --system aiva && useradd --system --gid aiva --create-home aiva \
    && groupadd --system --gid 6666 sandbox \
    && for i in $(seq 0 31); do \
         useradd --system --uid $((6666 + i)) --gid sandbox \
           --no-create-home --shell /usr/sbin/nologin "sandbox$i"; \
       done

EXPOSE 9200
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9200"]
