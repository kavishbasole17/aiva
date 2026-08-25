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

COPY --from=builder /install /usr/local
COPY prompts ./prompts

RUN groupadd --system aiva && useradd --system --gid aiva --create-home aiva
USER aiva

EXPOSE 9100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9100"]
