import os
import sys
import csv
import time
import re
import subprocess
from datetime import datetime, timedelta

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except Exception as e:
    print("Tkinter not available:", e)
    sys.exit(1)


# --------------------- ADB helpers ---------------------
def run_cmd(cmd, timeout=5):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            shell=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"Command failed: {' '.join(cmd)}")
        return result.stdout
    except FileNotFoundError:
        raise RuntimeError("找不到 adb。請先安裝 Android Platform Tools 並將 adb 加入 PATH。")
    except subprocess.TimeoutExpired:
        raise RuntimeError("執行 adb 逾時，請確認裝置連線正常。")


def list_adb_devices():
    out = run_cmd(["adb", "devices"])
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    devices = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def parse_battery_temp_from_dumpsys(text):
    for line in text.splitlines():
        line = line.strip().lower()
        if line.startswith("temperature:"):
            try:
                val = line.split(":", 1)[1].strip()
                t_tenths = float(val)
                return t_tenths / 10.0
            except Exception:
                continue
    return None


def get_phone_temperature(serial):
    out = run_cmd(["adb", "-s", serial, "shell", "dumpsys", "battery"])
    temp_c = parse_battery_temp_from_dumpsys(out)
    if temp_c is not None:
        return temp_c

    candidate_paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
        "/sys/class/power_supply/battery/temp",
    ]
    for path in candidate_paths:
        try:
            out = run_cmd(["adb", "-s", serial, "shell", "cat", path])
            raw = out.strip()
            if not raw:
                continue
            val = float(raw)
            if val > 1000:
                return val / 1000.0
            if val > 100:
                return val / 10.0
            return val
        except Exception:
            continue
    raise RuntimeError("無法讀取手機溫度 (dumpsys/thermal 路徑皆失敗)")


# --------------------- Memory helpers ---------------------
def parse_meminfo(text):
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        nums = re.findall(r"\d+", val)
        if nums:
            info[key] = float(nums[0])  # usually in kB
    return info


def get_system_memory_kb(serial):
    out = run_cmd(["adb", "-s", serial, "shell", "cat", "/proc/meminfo"])
    data = parse_meminfo(out)
    total = data.get("MemTotal", 0.0)
    avail = data.get("MemAvailable", 0.0)
    if avail <= 0:
        avail = data.get("MemFree", 0.0) + data.get("Cached", 0.0) + data.get("Buffers", 0.0)
    used = max(total - avail, 0.0)
    return {"total_kb": total, "free_kb": avail, "used_kb": used}


def _read_proc_stat_total(serial):
    txt = run_cmd(["adb", "-s", serial, "shell", "cat", "/proc/stat"]) 
    total = 0
    ncpu = 0
    for line in txt.splitlines():
        if line.startswith("cpu "):
            parts = line.split()
            nums = [float(x) for x in parts[1:]]
            total = sum(nums)
        elif line.startswith("cpu") and line[3:].strip()[:1].isdigit():
            ncpu += 1
    if ncpu == 0:
        ncpu = 1
    return total, ncpu


def _read_proc_pid_stat(serial, pid):
    txt = run_cmd(["adb", "-s", serial, "shell", "cat", f"/proc/{pid}/stat"]) 
    rparen = txt.rfind(')')
    rest = txt[rparen+2:] if rparen != -1 else txt
    parts = rest.split()
    try:
        utime = float(parts[11])
        stime = float(parts[12])
        cutime = float(parts[13])
        cstime = float(parts[14])
        return utime + stime + cutime + cstime
    except Exception:
        return None


def _get_page_size_kb(serial):
    try:
        out = run_cmd(["adb", "-s", serial, "shell", "getconf", "PAGESIZE"], timeout=3)
        v = out.strip()
        ps = float(v) / 1024.0
        if ps > 0:
            return ps
    except Exception:
        pass
    return 4096.0 / 1024.0


def _get_pid_for_package(serial, package):
    try:
        out = run_cmd(["adb", "-s", serial, "shell", "pidof", package], timeout=3)
        pids = [p for p in out.strip().split() if p.isdigit()]
        if pids:
            return pids[0]
    except Exception:
        pass
    try:
        out = run_cmd(["adb", "-s", serial, "shell", "ps", "-A"]) 
        cand = None
        for line in out.splitlines():
            if package in line:
                cols = line.split()
                for token in cols:
                    if token.isdigit():
                        cand = token
                        break
                if cand:
                    return cand
    except Exception:
        pass
    return None


def _read_statm_mb(serial, pid, page_kb):
    try:
        out = run_cmd(["adb", "-s", serial, "shell", "cat", f"/proc/{pid}/statm"]) 
        parts = out.strip().split()
        if len(parts) >= 3:
            size = float(parts[0]) * page_kb / 1024.0
            resident = float(parts[1]) * page_kb / 1024.0
            shared = float(parts[2]) * page_kb / 1024.0
            return size, resident, shared
    except Exception:
        pass
    return None, None, None


def get_process_metrics(serial, package, cpu_prev_cache):
    result = {
        'pid': None,
        'virt_mb': None,
        'res_mb': None,
        'shr_mb': None,
        'cpu_percent': None,
        'mem_percent': None,
        'error_message': '',
    }
    try:
        pid = _get_pid_for_package(serial, package)
        if not pid:
            result['error_message'] = '找不到進程'
            return result
        result['pid'] = int(pid)

        page_kb = _get_page_size_kb(serial)
        virt_mb, res_mb, shr_mb = _read_statm_mb(serial, pid, page_kb)
        result['virt_mb'] = virt_mb
        result['res_mb'] = res_mb
        result['shr_mb'] = shr_mb

        total_1, ncpu = _read_proc_stat_total(serial)
        proc_1 = _read_proc_pid_stat(serial, pid)
        prev = cpu_prev_cache.get(pid)
        cpu_percent = None
        if prev and proc_1 is not None:
            d_proc = max(proc_1 - prev['proc'], 0.0)
            d_total = max(total_1 - prev['total'], 1e-6)
            cpu_percent = (d_proc / d_total) * 100.0 * ncpu
        cpu_prev_cache.clear()
        cpu_prev_cache[pid] = {'proc': proc_1 if proc_1 is not None else 0.0, 'total': total_1}
        result['cpu_percent'] = cpu_percent

        meminfo = get_system_memory_kb(serial)
        if res_mb is not None and meminfo['total_kb']:
            result['mem_percent'] = (res_mb * 1024.0) / meminfo['total_kb'] * 100.0

        return result
    except Exception as e:
        result['error_message'] = str(e)
        return result


# --------------------- UI app ---------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("手機溫度/記憶體監控 (Python)")
        self.geometry("640x420")
        self.minsize(560, 360)
        self.resizable(True, True)
        self.bind("<Configure>", self._on_resize)

        self.refresh_ms = tk.IntVar(value=2000)
        self.is_running = False
        self.job_after_id = None
        self.selected_device = tk.StringVar(value="")
        self.current_temp = tk.StringVar(value="--")
        self.mem_usage_pct = tk.StringVar(value="--")
        self.mem_avail_mb = tk.StringVar(value="--")
        self.mem_total_mb = tk.StringVar(value="--")
        self.app_pss_mb = tk.StringVar(value="--")
        self.status_text = tk.StringVar(value="待機中")
        self.logging_enabled = tk.BooleanVar(value=True)
        self.package_name = tk.StringVar(value="")

        # logging/rotation
        self.log_root = os.path.join(os.getcwd(), "logs")
        self.current_log_dir = None
        self.current_log_path = None
        self._cpu_prev = {}

        self._build_ui()
        self._populate_devices()
        self._update_log_target(datetime.now())

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content = ttk.Frame(self, padding=(16, 16, 16, 16))
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)
        content.columnconfigure(2, weight=1)

        row = 0
        ttk.Label(content, text="裝置:").grid(row=row, column=0, sticky="e", **pad)
        self.device_combo = ttk.Combobox(content, textvariable=self.selected_device, state="readonly")
        self.device_combo.grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(content, text="重新整理裝置", command=self._populate_devices).grid(row=row, column=2, sticky="ew", **pad)

        row += 1
        ttk.Label(content, text="更新頻率(ms):").grid(row=row, column=0, sticky="e", **pad)
        self.refresh_entry = ttk.Spinbox(
            content,
            from_=500,
            to=60000,
            increment=500,
            textvariable=self.refresh_ms,
            width=10,
        )
        self.refresh_entry.grid(row=row, column=1, sticky="w", **pad)
        ttk.Checkbutton(content, text="寫入CSV紀錄", variable=self.logging_enabled).grid(row=row, column=2, sticky="w", **pad)

        row += 1
        ttk.Label(content, text="App 套件(可選):").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(content, textvariable=self.package_name).grid(row=row, column=1, sticky="ew", **pad)
        self.package_hint = ttk.Label(content, text="(紀錄 App PSS/CPU/MEM)")
        self.package_hint.grid(row=row, column=2, sticky="w", **pad)

        row += 1
        ttk.Label(content, text="目前溫度(°C):", font=("Segoe UI", 11, "bold")).grid(row=row, column=0, sticky="e", **pad)
        self.temp_label = ttk.Label(content, textvariable=self.current_temp, font=("Consolas", 16, "bold"))
        self.temp_label.grid(row=row, column=1, sticky="w", **pad)

        row += 1
        ttk.Label(content, text="系統記憶體使用率:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Label(content, textvariable=self.mem_usage_pct, font=("Consolas", 12)).grid(row=row, column=1, sticky="w", **pad)

        row += 1
        ttk.Label(content, text="可用/總記憶體(MB):").grid(row=row, column=0, sticky="ne", **pad)
        mem_frame = ttk.Frame(content)
        mem_frame.grid(row=row, column=1, columnspan=2, sticky="ew", **pad)
        mem_frame.columnconfigure(1, weight=1)
        mem_frame.columnconfigure(3, weight=1)
        ttk.Label(mem_frame, text="可用:").grid(row=0, column=0, sticky="e", padx=(0, 6))
        ttk.Label(mem_frame, textvariable=self.mem_avail_mb, font=("Consolas", 12)).grid(row=0, column=1, sticky="w")
        ttk.Label(mem_frame, text="總計:").grid(row=0, column=2, sticky="e", padx=(12, 6))
        ttk.Label(mem_frame, textvariable=self.mem_total_mb, font=("Consolas", 12)).grid(row=0, column=3, sticky="w")

        row += 1
        ttk.Label(content, text="App PSS(MB):").grid(row=row, column=0, sticky="e", **pad)
        ttk.Label(content, textvariable=self.app_pss_mb, font=("Consolas", 12)).grid(row=row, column=1, sticky="w", **pad)

        row += 1
        ttk.Label(content, text="狀態:").grid(row=row, column=0, sticky="ne", **pad)
        self.status_label = ttk.Label(content, textvariable=self.status_text, wraplength=320, justify="left")
        self.status_label.grid(row=row, column=1, columnspan=2, sticky="nsew", **pad)
        content.rowconfigure(row, weight=1)

        row += 1
        button_frame = ttk.Frame(content)
        button_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)

        self.start_btn = ttk.Button(button_frame, text="開始", command=self.start)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(button_frame, text="停止", command=self.stop).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _on_resize(self, event):
        if event.widget is not self:
            return
        wrap_padding = 240
        wraplength = max(event.width - wrap_padding, 220)
        self.status_label.configure(wraplength=wraplength)
        if hasattr(self, "package_hint"):
            hint_padding = 360
            self.package_hint.configure(wraplength=max(event.width - hint_padding, 160))

    def _populate_devices(self):
        try:
            devices = list_adb_devices()
            self.device_combo["values"] = devices
            if devices and (self.selected_device.get() not in devices):
                self.selected_device.set(devices[0])
            if not devices:
                self.selected_device.set("")
                self.status_text.set("找不到裝置，請確認 adb 連線。")
            else:
                self.status_text.set(f"已找到 {len(devices)} 台裝置。")
        except Exception as e:
            self.device_combo["values"] = []
            self.selected_device.set("")
            self.status_text.set(str(e))

    def _ensure_log_header_for(self, path):
        if not os.path.exists(path):
            try:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "timestamp_local",
                        "timestamp_iso8601",
                        "adb_sys_total_kb",
                        "adb_sys_used_kb",
                        "adb_sys_free_kb",
                        "adb_proc_pid",
                        "adb_proc_virt_mb",
                        "adb_proc_res_mb",
                        "adb_proc_shr_mb",
                        "adb_proc_cpu_percent",
                        "adb_proc_mem_percent",
                        "error_message",
                    ])
            except Exception:
                pass

    def _update_log_target(self, now_dt):
        half_min = 30 if now_dt.minute >= 30 else 0
        dir_name = f"{now_dt.strftime('%Y%m%d')}_{now_dt.strftime('%H')}{half_min:02d}"
        log_dir = os.path.join(self.log_root, dir_name)

        five_min = (now_dt.minute // 5) * 5
        file_name = f"metrics_{now_dt.strftime('%Y%m%d')}_{now_dt.strftime('%H')}{five_min:02d}.csv"
        log_path = os.path.join(log_dir, file_name)

        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception:
            pass

        if log_path != self.current_log_path:
            self.current_log_dir = log_dir
            self.current_log_path = log_path
            self._ensure_log_header_for(self.current_log_path)

        self._cleanup_old_logs(hours=36)

    def _cleanup_old_logs(self, hours=36):
        threshold = time.time() - hours * 3600
        root = self.log_root
        if not os.path.exists(root):
            return
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    if os.path.getmtime(fp) < threshold:
                        os.remove(fp)
                except Exception:
                    continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            try:
                if not dirnames and not filenames:
                    os.rmdir(dirpath)
            except Exception:
                pass

    def start(self):
        if self.is_running:
            return
        if not self.selected_device.get():
            messagebox.showwarning("提示", "請先選擇一台裝置。")
            return
        try:
            ms = int(self.refresh_ms.get())
            if ms < 200:
                raise ValueError
        except Exception:
            messagebox.showwarning("提示", "請輸入有效的更新頻率 (>=200 毫秒)。")
            return

        self.is_running = True
        self.status_text.set("監控中…")
        self.start_btn.configure(state="disabled")
        self._schedule_next()

    def stop(self):
        self.is_running = False
        if self.job_after_id is not None:
            try:
                self.after_cancel(self.job_after_id)
            except Exception:
                pass
            self.job_after_id = None
        self.start_btn.configure(state="normal")
        self.status_text.set("已停止")

    def _schedule_next(self):
        if not self.is_running:
            return
        delay = int(self.refresh_ms.get())
        self.job_after_id = self.after(delay, self._tick)

    def _tick(self):
        serial = self.selected_device.get()
        if not serial:
            self.status_text.set("沒有選擇裝置。")
            self.stop()
            return
        try:
            now_dt = datetime.now()
            self._update_log_target(now_dt)

            temp_c = get_phone_temperature(serial)
            self.current_temp.set(f"{temp_c:.1f}")

            sys_mem = get_system_memory_kb(serial)
            self.mem_total_mb.set(f"{sys_mem['total_kb']/1024:.0f}")
            self.mem_avail_mb.set(f"{sys_mem['free_kb']/1024:.0f}")
            used_pct = (sys_mem['used_kb'] / sys_mem['total_kb'] * 100.0) if sys_mem['total_kb'] else 0.0
            self.mem_usage_pct.set(f"{used_pct:.1f}%")

            pkg = self.package_name.get().strip()
            proc = get_process_metrics(serial, pkg, self._cpu_prev) if pkg else None
            if proc and proc.get('res_mb') is not None:
                self.app_pss_mb.set(f"{proc['res_mb']:.1f}")
            else:
                self.app_pss_mb.set("--")

            ts_local = now_dt.strftime('%Y-%m-%d %H:%M:%S')
            ts_iso = now_dt.astimezone().isoformat(timespec='seconds')
            line = [
                ts_local,
                ts_iso,
                f"{int(sys_mem['total_kb'])}",
                f"{int(sys_mem['used_kb'])}",
                f"{int(sys_mem['free_kb'])}",
                str(proc['pid']) if proc and proc.get('pid') is not None else "",
                f"{proc['virt_mb']:.1f}" if proc and proc.get('virt_mb') is not None else "",
                f"{proc['res_mb']:.1f}" if proc and proc.get('res_mb') is not None else "",
                f"{proc['shr_mb']:.1f}" if proc and proc.get('shr_mb') is not None else "",
                f"{proc['cpu_percent']:.1f}" if proc and proc.get('cpu_percent') is not None else "",
                f"{proc['mem_percent']:.1f}" if proc and proc.get('mem_percent') is not None else "",
                proc.get('error_message', '') if proc else "",
            ]
            print(','.join(line))

            self._maybe_log(sys_mem, proc, now_dt)
            self.status_text.set(f"最後更新: {now_dt.strftime('%H:%M:%S')}")
        except Exception as e:
            self.status_text.set(str(e))
        finally:
            self._schedule_next()

    def _maybe_log(self, sys_mem, proc, now_dt):
        if not self.logging_enabled.get():
            return
        try:
            if not self.current_log_path:
                self._update_log_target(now_dt)
            with open(self.current_log_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                ts_local = now_dt.strftime('%Y-%m-%d %H:%M:%S')
                ts_iso = now_dt.astimezone().isoformat(timespec='seconds')
                writer.writerow([
                    ts_local,
                    ts_iso,
                    int(sys_mem['total_kb']),
                    int(sys_mem['used_kb']),
                    int(sys_mem['free_kb']),
                    (proc.get('pid') if proc else ''),
                    (f"{proc['virt_mb']:.1f}" if proc and proc.get('virt_mb') is not None else ''),
                    (f"{proc['res_mb']:.1f}" if proc and proc.get('res_mb') is not None else ''),
                    (f"{proc['shr_mb']:.1f}" if proc and proc.get('shr_mb') is not None else ''),
                    (f"{proc['cpu_percent']:.1f}" if proc and proc.get('cpu_percent') is not None else ''),
                    (f"{proc['mem_percent']:.1f}" if proc and proc.get('mem_percent') is not None else ''),
                    (proc.get('error_message', '') if proc else ''),
                ])
        except Exception as e:
            self.status_text.set(f"寫入紀錄失敗: {e}")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
