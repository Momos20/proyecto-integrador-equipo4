#!/usr/bin/env bash
# Arranque idempotente de la app AWS de CineGraph. Se ejecuta COMO ROOT en EC2
# mediante AWS Systems Manager, nunca desde CloudShell directamente.
# No publica puertos ni escribe secretos en la terminal o repositorio.
set -euo pipefail
umask 077

REPO_DIR=/opt/cinegraph/source
RUNTIME=/opt/cinegraph/runtime
COMPOSE="$REPO_DIR/infrastructure/aws/compose.web.yaml"

: "${RDS_ENDPOINT:?Falta RDS_ENDPOINT; obtenerlo de CloudFormation en CloudShell}"
if [[ "$RDS_ENDPOINT" != cinegraph-e4-postgres.*.us-east-1.rds.amazonaws.com ]]; then
  echo RDS_ENDPOINT_NO_AUTORIZADO >&2
  exit 2
fi

docker image inspect cinegraph-e4-app:main >/dev/null
test -f "$COMPOSE"
install -d -m 0700 "$RUNTIME" "$RUNTIME/clickstream"

python3 - <<'PY'
import os
import secrets
from pathlib import Path

key = Path("/opt/cinegraph/runtime/session_key")
if not key.exists():
    descriptor = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secrets.token_urlsafe(48))
elif len(key.read_text(encoding="utf-8").strip()) < 48:
    raise RuntimeError("SESSION_KEY_INVALID")
key.chmod(0o600)
print("SESSION_KEY_PRESENT")
PY

docker compose -p cinegraph-e4 -f "$COMPOSE" config --quiet
docker compose -p cinegraph-e4 -f "$COMPOSE" up -d --no-build --wait --wait-timeout 120

docker compose -p cinegraph-e4 -f "$COMPOSE" ps

python3 - <<'PY'
import json
from urllib.request import urlopen

base = "http://127.0.0.1:8000"

def request(path):
    with urlopen(base + path, timeout=8) as response:
        if response.status != 200:
            raise RuntimeError("HTTP_STATUS_UNEXPECTED")
        return json.load(response)

if request("/health").get("status") != "ok":
    raise RuntimeError("HEALTH_FAILED")
print("HTTP_HEALTH_OK")

if request("/api/ready").get("database") != "ok":
    raise RuntimeError("RDS_NOT_READY")
print("HTTP_RDS_READY_OK")

catalog = request("/api/catalog?limit=2")
if not catalog.get("ready") or catalog.get("count") != 2:
    raise RuntimeError("CATALOG_NOT_READY")
print("HTTP_MOVIELENS_CATALOG_OK: 2")
print("CINEGRAPH_WEB_LOCAL_READY: sin acceso publico")
PY
