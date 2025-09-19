#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_PATH="${SCRIPT_DIR}/phone_temp_monitor.py"

if [[ ! -f "${APP_PATH}" ]]; then
  echo "[錯誤] 找不到 phone_temp_monitor.py (位置: ${APP_PATH})" >&2
  exit 1
fi

if [[ -x "${SCRIPT_DIR}/.venv/bin/python" ]]; then
  PYTHON="${SCRIPT_DIR}/.venv/bin/python"
else
  if command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
  else
    echo "[錯誤] 找不到 Python 執行檔 (python3 / python)。請先安裝 Python 3.10 以上版本。" >&2
    exit 1
  fi
fi

# 檢查 tkinter 是否可用
"${PYTHON}" - <<'PY'
import sys
try:
    import tkinter  # noqa: F401
except Exception as exc:
    print("[錯誤] Tkinter 無法使用: {}".format(exc), file=sys.stderr)
    print("請依 README 的安裝步驟重新安裝 Python/Tk。", file=sys.stderr)
    sys.exit(1)
PY

# 檢查 adb 是否存在
if ! command -v adb >/dev/null 2>&1; then
  echo "[警告] 找不到 adb 指令，請確認已安裝 Android Platform Tools 並設定 PATH。" >&2
fi

echo "使用 Python: ${PYTHON}"
echo "啟動手機溫度/記憶體監控介面..."
exec "${PYTHON}" "${APP_PATH}" "$@"
