#!/usr/bin/with-contenv bashio
# Home Assistant add-on entry point: map add-on options to environment variables.
# Falls back to plain defaults when run outside the Supervisor (e.g. `docker run ... /run.sh`).
set -e

OPTIONS=/data/options.json
opt() {  # opt <key> <default>
  local v=""
  if [ -f "$OPTIONS" ]; then
    v="$(jq -r --arg k "$1" '.[$k] // empty' "$OPTIONS" 2>/dev/null || true)"
  fi
  if [ -z "$v" ] || [ "$v" = "null" ]; then v="$2"; fi
  printf '%s' "$v"
}

SSI_EMAIL="$(opt ssi_email '')"
SSI_PASSWORD="$(opt ssi_password '')"
[ -n "$SSI_EMAIL" ] && export SSI_EMAIL
[ -n "$SSI_PASSWORD" ] && export SSI_PASSWORD
export DIVEBRIDGE_OUTPUT_DIR="$(opt output_dir /share/divebridge/uddf)"
mkdir -p "$DIVEBRIDGE_OUTPUT_DIR" 2>/dev/null || true
export DIVEBRIDGE_DATA_DIR="${DIVEBRIDGE_DATA_DIR:-/data/divebridge}"
export DIVEBRIDGE_INGRESS_ONLY="${DIVEBRIDGE_INGRESS_ONLY:-1}"
LOG_LEVEL="$(opt log_level info)"

echo "[divebridge] starting on port 8099 (ingress only: ${DIVEBRIDGE_INGRESS_ONLY}, output: ${DIVEBRIDGE_OUTPUT_DIR})"
# no --proxy-headers: the ingress guard must see the real peer (HA core, 172.30.32.2), not X-Forwarded-For
exec python -m uvicorn divebridge.web.app:app --host 0.0.0.0 --port 8099 --log-level "${LOG_LEVEL}"
