#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ $# -lt 1 || ( "$1" != "he" && "$1" != "hn" ) ]]; then
    echo "Uso: $0 he|hn [--debug]" >&2
    exit 2
fi

if [[ -f config.env ]]; then
    set -a
    # shellcheck disable=SC1091
    source <(sed 's/\r$//' config.env)
    set +a
elif [[ -z "${GLPI_API_URL:-}" || -z "${GLPI_APP_TOKEN:-}" || -z "${GLPI_USER_TOKEN:-}" ]]; then
    echo "Arquivo config.env nao encontrado. Copie config.env.example para config.env e preencha." >&2
    exit 1
fi

exec python3 glpi_report.py "$@"
