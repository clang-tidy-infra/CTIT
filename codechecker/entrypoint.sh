#!/usr/bin/env bash
# Entrypoint for the CodeChecker server container.
# Renders /workspace/server_config.json on first start from env vars and launches
# `CodeChecker server` wired to the postgres service.
set -euo pipefail

WORKSPACE=${WORKSPACE:-/workspace}
export SERVER_CONFIG="$WORKSPACE/server_config.json"

mkdir -p "$WORKSPACE"

if [[ ! -f "$SERVER_CONFIG" ]]; then
  echo "[entrypoint] Generating $SERVER_CONFIG"
  python3 - <<'PY'
import json
import os

config = {
    "authentication": {
        "enabled": True,
        "realm_name": "CTIT CodeChecker",
        "realm_error": "Authentication required.",
        "logins_until_cleanup": 30,
        "session_lifetime": 2592000,
        "refresh_time": 60,
        "method_dictionary": {
            "enabled": True,
            "auths": [
                f"{os.environ['CODECHECKER_SUPERUSER']}:{os.environ['CODECHECKER_SUPERUSER_PASSWORD']}"
            ],
            "groups": {
                os.environ["CODECHECKER_SUPERUSER"]: ["admin"]
            },
        },
        "regex_groups": {"enabled": False},
        "super_user": os.environ["CODECHECKER_SUPERUSER"],
    },
    "store": {"analysis_statistics_dir": None},
    "keepalive": {"enabled": True},
}
with open(os.environ["SERVER_CONFIG"], "w") as f:
    json.dump(config, f, indent=2)
PY
fi

echo "[entrypoint] Launching CodeChecker server on :8001"
exec CodeChecker server \
  --workspace "$WORKSPACE" \
  --config-directory "$WORKSPACE" \
  --listen 0.0.0.0 \
  --port 8001 \
  --not-host-only \
  --postgresql \
  --dbaddress postgres \
  --dbport 5432 \
  --dbusername codechecker \
  --dbpassword "$POSTGRES_PASSWORD" \
  --dbname codechecker
