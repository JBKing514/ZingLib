# Base images are pinned by digest: a floating tag can be republished, which
# makes "v1.0.0" build to different contents on different days. Bump the digest
# deliberately, in its own commit. Read the current one with:
#   docker images --digests python:3.11-slim node:22-bookworm-slim
FROM node:22-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9 AS webbuild

WORKDIR /webapp
COPY webapp/package.json /webapp/package.json
# package-lock.json is a build input: `npm ci` installs exactly the tree the
# lockfile records and fails if it disagrees with package.json. `npm install`
# would instead resolve ranges fresh, so the same Dockerfile could produce a
# different bundle on a different day.
COPY webapp/package-lock.json /webapp/package-lock.json
COPY webapp/index.html /webapp/index.html
COPY webapp/vite.config.js /webapp/vite.config.js
COPY webapp/src /webapp/src
# public/ is a build input: it carries version.json and the PWA icons that the
# manifest points at. Omitting it silently shipped an image without them.
COPY webapp/public /webapp/public
RUN npm ci --no-audit --no-fund && npm run build

FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    bash \
    curl \
    ca-certificates \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install -r /app/requirements.txt

COPY textIngest /app/textIngest
COPY vectorIngest /app/vectorIngest
COPY webapi /app/webapi
COPY --from=webbuild /webapp/dist /app/webapi/static
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x \
    /app/entrypoint.sh \
    /app/textIngest/run_daily_text_ingest.sh \
    /app/textIngest/run_migrations.sh
EXPOSE 8501
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["help"]
