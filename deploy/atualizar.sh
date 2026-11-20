#!/usr/bin/env bash
# Atualiza o SeuLaudoai no servidor com a última versão do GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
