#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="${SCRIPT_DIR}/.venv"

log() { printf '==> %s\n' "$*"; }
err() { printf '[錯誤] %s\n' "$*" >&2; }
warn() { printf '[警告] %s\n' "$*" >&2; }

demand_python() {
  local candidates=("${SCRIPT_DIR}/.venv/bin/python" python3 python)
  local chosen=""
  for cmd in "${candidates[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
      chosen="$(command -v "$cmd")"
      break
    fi
  done
  if [[ -z "$chosen" ]]; then
    err "找不到可用的 Python。請先安裝 Python 3.10 以上版本，再重新執行此腳本。"
    exit 1
  fi
  echo "$chosen"
}

check_version() {
  local py="$1"
  local ver
  ver="$("$py" - <<'PY'
import sys
print('.'.join(map(str, sys.version_info[:3])))
PY
)" || {
    err "無法讀取 Python 版本 (使用: $py)。"
    exit 1
  }
  log "偵測到 Python 版本: $ver"
  IFS=. read -r major minor patch <<< "$ver"
  if (( major < 3 || (major == 3 && minor < 10) )); then
    err "需要 Python 3.10 以上版本 (目前: $ver)。請更新後再執行。"
    exit 1
  fi
}

check_tk() {
  local py="$1"
  "$py" - <<'PY'
try:
    import tkinter
except Exception as exc:
    raise SystemExit(str(exc))
PY
  if [[ $? -ne 0 ]]; then
    err "目前的 Python 無法載入 Tkinter。請依 README 的安裝步驟重新安裝 Python/Tk。"
    exit 1
  fi
  log "Tkinter 檢查通過。"
}

create_venv() {
  local py="$1"
  if [[ -d "$ENV_DIR" ]]; then
    log "偵測到既有虛擬環境 (.venv)，略過建立步驟。"
  else
    log "建立虛擬環境 (.venv)。"
    "$py" -m venv "$ENV_DIR"
  fi
}

post_setup() {
  local venv_py="$ENV_DIR/bin/python"
  if [[ ! -x "$venv_py" ]]; then
    err "虛擬環境建立失敗，找不到 $venv_py。"
    exit 1
  fi
  log "升級 pip..."
  "$venv_py" -m pip install --upgrade pip >/dev/null
  log "虛擬環境準備完成，可執行: source .venv/bin/activate"
}

check_adb() {
  if ! command -v adb >/dev/null 2>&1; then
    warn "找不到 adb，請安裝 Android Platform Tools 並設定 PATH。"
  else
    log "已偵測到 adb: $(command -v adb)"
  fi
}

main() {
  local py
  py="$(demand_python)"
  log "使用 Python 執行檔: $py"
  check_version "$py"
  check_tk "$py"
  create_venv "$py"
  post_setup
  check_adb
  log "環境安裝步驟完成。若要啟動程式，請執行 ./run.sh"
}

main "$@"
