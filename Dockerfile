# One image: FastAPI + the built UI on a single port. See docs/DEPLOY.md.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
COPY api/ api/
COPY eval/ eval/
COPY scripts/ scripts/
COPY hack_the_highway/ hack_the_highway/
COPY agents.toml ./
COPY traces/examples/ traces/examples/
COPY --from=ui /ui/dist ui/dist
RUN uv sync --frozen --no-dev && mkdir -p runs/live traces/live && chmod +x scripts/docker-entrypoint.sh
ENV TRACES_DIR=traces/live RUN_DIR=runs/live UI_DIST=ui/dist PORT=8080
EXPOSE 8080
# same as: uv run uvicorn api.app:app --host 0.0.0.0 --port ${PORT}; the script first links volume paths if configured
CMD ["scripts/docker-entrypoint.sh"]
