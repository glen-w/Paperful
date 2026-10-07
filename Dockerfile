# paperful — optional runtime pack (CLI against host Zotero).
# syntax=docker/dockerfile:1
#
# PAPERFUL_IMAGE_MODE:
#   light (default) — core + [serve] (CI / stranger path)
#   heavy           — also [llm] [rag] [browser-agent] for a full local env

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

WORKDIR /build
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY pyproject.toml uv.lock README.md ./
COPY paperful ./paperful

ARG PAPERFUL_IMAGE_MODE=light
RUN --mount=type=cache,target=/root/.cache/uv \
    case "${PAPERFUL_IMAGE_MODE}" in \
      light) \
        uv sync --no-dev --no-editable --extra serve \
          --reinstall-package paperful ;; \
      heavy) \
        uv sync --no-dev --no-editable \
          --extra serve --extra llm --extra rag --extra browser-agent \
          --reinstall-package paperful ;; \
      *) \
        echo "Unknown PAPERFUL_IMAGE_MODE=${PAPERFUL_IMAGE_MODE} (use light|heavy)" >&2; \
        exit 1 ;; \
    esac

FROM python:3.12-slim-bookworm AS runtime

ARG PAPERFUL_IMAGE_MODE=light
LABEL org.opencontainers.image.title="paperful" \
      paperful.image.mode="${PAPERFUL_IMAGE_MODE}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        ocrmypdf \
        tesseract-ocr \
        tesseract-ocr-eng \
        ghostscript \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    PAPERFUL_ZOTERO_HOST=host.docker.internal \
    PAPERFUL_IMAGE_MODE=${PAPERFUL_IMAGE_MODE}

# Chromium + OS libs for htmlpdf / session vault reuse.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 paperful \
    && mkdir -p /data /opt/ms-playwright \
    && chown -R paperful:paperful /data /opt/ms-playwright

WORKDIR /data
USER paperful

ENTRYPOINT ["paperful"]
CMD ["doctor"]
