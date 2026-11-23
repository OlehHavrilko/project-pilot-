#!/usr/bin/env bash
# Control the Windows bridge from WSL: deploy / start / stop / status / logs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PS="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
CMD="/mnt/c/Windows/System32/cmd.exe"

if [[ ! -x "$PS" ]]; then
    cat >&2 <<'EOF'
Windows drives are not mounted. Run:
  sudo mount -t drvfs C: /mnt/c && sudo mount -t drvfs D: /mnt/d
(or enable automount in /etc/wsl.conf)
EOF
    exit 1
fi

ACTION="${1:-deploy}"
[[ $# -gt 0 ]] && shift

TOKEN="$(grep -E '^PILOT_BRIDGE_TOKEN=' "$ROOT/.env" | head -1 | cut -d= -f2- || true)"
if [[ -z "$TOKEN" ]]; then
    echo "PILOT_BRIDGE_TOKEN is missing in $ROOT/.env" >&2
    exit 1
fi

LOCALAPP_DATA_WIN="$("$CMD" /c 'echo %LOCALAPPDATA%' 2>/dev/null | tr -d '\r' | tail -1)"
LOCALAPP_DATA="$(wslpath -u "$LOCALAPP_DATA_WIN")"
INSTALL_DIR="$LOCALAPP_DATA/pilot-bridge"
INSTALL_DIR_WIN="$LOCALAPP_DATA_WIN\\pilot-bridge"
mkdir -p "$INSTALL_DIR/logs"
printf '%s' "$TOKEN" > "$INSTALL_DIR/token.txt"

WINHOST="$(ip route show default | awk '/via/ {print $3; exit}')"
if [[ -z "$WINHOST" ]]; then
    echo "Cannot determine the Windows host address (mirrored networking?)" >&2
    [[ "${PILOT_BRIDGE_URL:-}" == *"127.0.0.1"* ]] && WINHOST=127.0.0.1 || { echo "Set PILOT_BRIDGE_URL and run manually" >&2; exit 1; }
fi
SOURCE_WIN="$(wslpath -w "$ROOT/win_bridge")"

case "$ACTION" in
    logs)
        tail -n 80 "$INSTALL_DIR"/logs/bridge.*.log
        exit 0
        ;;
    deploy|start|stop|status)
        "$PS" -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$ROOT/scripts/deploy_bridge.ps1")" \
            -Action "$ACTION" \
            -SourcePath "$SOURCE_WIN" \
            -InstallDir "$INSTALL_DIR_WIN" \
            -ListenHost "${PILOT_BRIDGE_LISTEN_HOST:-$WINHOST}" \
            -Port "${PILOT_BRIDGE_PORT:-8765}" \
            -AudioDevice "${PILOT_AUDIO_DEVICE:-}" \
            "$@"
        ;;
    *)
        echo "usage: $0 {deploy|start|stop|status|logs}" >&2
        exit 2
        ;;
esac

if [[ "$ACTION" == "deploy" || "$ACTION" == "start" ]]; then
    echo "PILOT_BRIDGE_URL=http://$WINHOST:${PILOT_BRIDGE_PORT:-8765}"
fi
