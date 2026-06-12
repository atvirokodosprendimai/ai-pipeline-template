# Containerized deploy option (alternative to the systemd unit).
# The whole service runs in the container; mount secrets via --env-file.
# (A per-Goose-run sandbox — running each goose invocation in its own throwaway
# container — is a follow-up; this image runs the service itself.)
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates bzip2 unzip xz-utils \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL https://github.com/block/goose/releases/latest/download/download_cli.sh | bash

WORKDIR /app
COPY pipeline/ /app/pipeline/
RUN pip install --no-cache-dir -e /app/pipeline

# Non-root: the container holds the bot PAT; shrink the blast radius.
RUN useradd --system --uid 10001 wgmesh && chown -R wgmesh /app
USER wgmesh

# PIPELINE_MODE / secrets supplied at runtime via --env-file (see env.example).
ENV PIPELINE_MODE=shadow
CMD ["python", "-m", "wgmesh_pipeline.main"]
