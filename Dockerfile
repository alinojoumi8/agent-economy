# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS dashboard-build
WORKDIR /src
COPY dashboard/package.json dashboard/package-lock.json ./dashboard/
RUN --mount=type=cache,target=/root/.npm npm ci --prefix dashboard
COPY dashboard ./dashboard
COPY server/static ./server/static
RUN npm run build --prefix dashboard

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AGENT_ECONOMY_HOSTED_CONFIG=/app/config/hosted.docker.yaml

RUN groupadd --gid 10001 agent-economy \
    && useradd --uid 10001 --gid agent-economy --create-home --shell /usr/sbin/nologin agent-economy

WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-cache-dir --require-hashes -r requirements.lock

COPY . .
COPY --from=dashboard-build /src/server/static ./server/static
RUN mkdir -p /var/lib/agent-economy/runs /var/lib/agent-economy/snapshots \
    && chown -R agent-economy:agent-economy /var/lib/agent-economy

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"

ENTRYPOINT ["python", "-m", "hosted.cli"]
CMD ["serve", "--config", "/app/config/hosted.docker.yaml", "--host", "0.0.0.0", "--port", "8000"]
