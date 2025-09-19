# 手機溫度/記憶體監控工具

以 Tkinter 製作的跨平台桌面介面，透過 `adb` 讀取 Android 裝置的電池溫度與記憶體資訊，並能選擇特定 App 觀察 PSS/CPU/記憶體占用，同步支援 CSV 紀錄與檔案輪替。

## 主要特色
- 自動列出所有以 `adb` 連線的裝置，可手動重新整理
- 即時顯示電池溫度、系統記憶體使用率與可用/總記憶體
- 指定套件名稱即可追蹤 App PID、PSS、CPU、MEM 指標
- 以 5 分鐘為粒度輸出 CSV，保留最近 36 小時的紀錄檔
- 介面可調整視窗尺寸，狀態訊息與提示會自動換行
- 手動設定更新頻率（500–60000ms），可隨時啟動/停止輪詢

## 系統需求
- macOS、Windows 或 Linux（需支援 `adb`）
- Python 3.10 以上版本，且能載入 Tkinter
- Android Platform Tools（確保終端機可直接呼叫 `adb`）

## 快速開始
本專案提供 `install_env.sh` 與 `run.sh` 兩支腳本協助環境建立與啟動流程。

```bash
# 1. 建立虛擬環境並檢查 Python/Tkinter 與 adb
./install_env.sh

# 2. 啟動桌面應用程式
./run.sh
```

> 若未使用腳本，可自行使用 `python -m venv .venv` 建立虛擬環境並手動啟動。

## 安裝流程說明
### 1. 準備 Android Platform Tools
1. 從 [Android 官方網站](https://developer.android.com/studio/releases/platform-tools) 下載 Platform Tools。
2. 解壓縮後將資料夾加入 PATH；macOS 使用者可改用 `brew install android-platform-tools`。
3. 以 `adb devices` 驗證裝置已成功連線並授權。

### 2. 安裝 Python（含 Tkinter）
- macOS：建議透過 Homebrew 安裝 `tcl-tk`，再搭配 `pyenv` 編譯 Python，使 Tkinter 使用新版 Tcl/Tk。
- Windows/Linux：確保 Python 版本 ≥3.10 且安裝時勾選 Tkinter（多數發行版預設包含）。

### 3. 建立虛擬環境
```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\\Scripts\\activate
```
專案僅依賴標準函式庫，不需額外 `pip install`。

## 使用方式
1. 連接 Android 裝置並開啟 USB 偵錯。
2. 執行 `python phone_temp_monitor.py` 或 `./run.sh`。
3. 在下拉選單選擇裝置，必要時按「重新整理裝置」。
4. 視需求調整輪詢頻率、是否寫入 CSV、及輸入欲監控的 App 套件名稱。
5. 按「開始」後程式即會輪詢資料並更新畫面與狀態列。
6. 按「停止」即可終止輪詢；主控台會同步列印每次輪詢的 CSV 行，方便即時觀察。

## CSV 紀錄
- 檔案儲存在 `logs/<日期_時間區段>/metrics_YYYYMMDD_HHMM.csv`
- 每 5 分鐘建立一個檔案、每 30 分鐘建立一個資料夾
- 超過 36 小時的紀錄會自動刪除
- 欄位包含時間戳、系統記憶體指標，以及（如有指定套件）App PID/PSS/CPU/MEM

## 疑難排解
- **找不到 adb**：確認 Platform Tools 已安裝並加入 PATH。
- **Tkinter not available**：依「安裝 Python」段落重新安裝，或改用 `./install_env.sh` 讓腳本檢查環境。
- **請先選擇一台裝置**：按「重新整理裝置」，或確認手機已允許除錯。
- **App 套件找不到進程**：確認套件名稱正確，且 App 仍在前景/背景執行。

## 參與貢獻
歡迎提交 Issue 與 Pull Request，建議遵循下列流程：
1. Fork 並建立分支
2. 以 `./run.sh` 驗證功能是否正常
3. 透過 `git commit` 撰寫清楚的訊息並附上說明

## 授權
本專案目前未設定授權，預設保留所有權利。若需商業或公開使用，請先聯繫作者。
