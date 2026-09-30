#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sysmonitor —— Ubuntu 桌面实时监控工具（GUI 版）

实时显示：
  - CPU 总体使用率及每核心使用率（进度条）
  - 内存 / Swap 使用情况
  - 上传、下载网速（含累计流量）
  - 系统运行时长

零第三方依赖（仅标准库 Tkinter + /proc），双击文件即可打开。
"""

import argparse
import json
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import font as tkfont

# 配置文件与应用同目录（打包后为可执行文件所在目录，源码运行为脚本所在目录）
CONFIG_PATH = os.path.join(
    os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                    else os.path.abspath(__file__)),
    "config.json",
)


def load_config():
    """读取保存的配置，返回 {} 表示无配置"""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
    except OSError:
        pass


def resource_path(name):
    """兼容源码运行与 PyInstaller 打包（onefile 解压到 _MEIPASS）"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# ---------------------------------------------------------------
# 数据采集层（读取 /proc）
# ---------------------------------------------------------------

def read_cpu_times():
    """读取 /proc/stat，返回 (总体时间列表, [每核心时间列表])"""
    cpus = {}
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu"):
                parts = line.split()
                cpus[parts[0]] = [int(x) for x in parts[1:]]
    total = cpus.get("cpu", [])
    per_core = [cpus[k] for k in sorted(
        (k for k in cpus if k != "cpu"),
        key=lambda s: int(s[3:]),
    )]
    return total, per_core


def cpu_usage(prev, cur):
    """根据两次采样计算使用率百分比（iowait 计入使用率）"""
    def usage(p, c):
        dp = sum(p)
        dc = sum(c)
        if dc - dp <= 0:
            return 0.0
        busy = (dc - dp) - (c[3] - p[3])
        return max(0.0, min(100.0, 100.0 * busy / (dc - dp)))
    return usage(prev, cur)


def read_mem():
    """读取 /proc/meminfo，返回内存与 Swap 信息（单位 MB）"""
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, val = line.split(":", 1)
            info[key] = float(val.strip().split()[0]) / 1024.0  # kB -> MB

    mem_total = info.get("MemTotal", 0.0)
    mem_avail = info.get("MemAvailable", info.get("MemFree", 0.0))
    swap_total = info.get("SwapTotal", 0.0)
    swap_free = info.get("SwapFree", 0.0)
    mem_used = mem_total - mem_avail
    swap_used = swap_total - swap_free
    return {
        "mem_total": mem_total,
        "mem_used": mem_used,
        "mem_pct": 100.0 * mem_used / mem_total if mem_total else 0.0,
        "swap_total": swap_total,
        "swap_used": swap_used,
        "swap_pct": 100.0 * swap_used / swap_total if swap_total else 0.0,
    }


def read_net():
    """读取 /proc/net/dev，返回 {网卡: (rx_bytes, tx_bytes)}，过滤 lo"""
    stats = {}
    with open("/proc/net/dev") as f:
        lines = f.readlines()[2:]
    for line in lines:
        if ":" not in line:
            continue
        iface, data = line.split(":", 1)
        iface = iface.strip()
        fields = data.split()
        if iface == "lo":
            continue
        stats[iface] = (int(fields[0]), int(fields[8]))
    return stats


def read_uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
    except (OSError, ValueError):
        return ""
    days, rem = divmod(int(secs), 86400)
    hours, rem = divmod(rem, 3600)
    return f"运行 {days}天{hours}时{rem // 60}分"


def format_speed(bps):
    if bps < 1024:
        return f"{bps:.0f} B/s"
    for unit in ("KB/s", "MB/s", "GB/s"):
        bps /= 1024.0
        if bps < 1024:
            return f"{bps:.2f} {unit}"
    return f"{bps:.2f} TB/s"


def format_bytes(b):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


# ---------------------------------------------------------------
# GUI 层
# ---------------------------------------------------------------

BG = "#1e1e2e"
FG = "#cdd6f4"
BAR_BG = "#313244"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
RED = "#f38ba8"
BLUE = "#89b4fa"
MAUVE = "#cba6f7"
SUBTEXT = "#9399b2"


def pct_color(pct):
    if pct < 60:
        return GREEN
    if pct < 85:
        return YELLOW
    return RED


class MonitorApp(tk.Tk):
    def __init__(self, interval=1.0):
        super().__init__(className="Sysmonitor")
        self.title("系统监控 - sysmonitor")
        self.configure(bg=BG)
        self.resizable(False, False)
        # 初始间隔：优先使用上次保存的值，否则用命令行参数
        saved = load_config().get("interval_sec")
        if isinstance(saved, (int, float)) and 1 <= saved <= 30:
            interval = saved
        self.interval = max(1, min(30, interval)) * 1000

        # 窗口图标
        try:
            self._icon = tk.PhotoImage(file=resource_path(
                os.path.join("assets", "icon.png")))
            self.iconphoto(True, self._icon)
        except tk.TclError:
            pass

        self.bar_width = 220
        self.bar_height = 18

        base = tkfont.nametofont("TkDefaultFont")
        base.configure(size=10)
        self.font_big = tkfont.Font(size=11, weight="bold")
        self.font_normal = tkfont.Font(size=10)
        self.font_mono = tkfont.Font(family="Monospace", size=10)
        self.font_small = tkfont.Font(family="Monospace", size=9)

        self.cpu_total_text = tk.StringVar(value="总体 --%")
        self.mem_text = tk.StringVar(value="--")
        self.swap_text = tk.StringVar(value="")

        container = tk.Frame(self, bg=BG, padx=16, pady=12)
        container.pack()

        # ---- 标题 ----
        self.title_label = tk.Label(
            container, text="", font=self.font_normal,
            bg=BG, fg=SUBTEXT, anchor="w",
        )
        self.title_label.pack(fill="x", pady=(0, 10))

        # ---- 刷新间隔（滑动选择，1-30 秒） ----
        interval_row = tk.Frame(container, bg=BG)
        interval_row.pack(anchor="w", pady=(0, 10))
        tk.Label(
            interval_row, text="刷新间隔", font=self.font_normal,
            bg=BG, fg=SUBTEXT,
        ).pack(side="left")
        self.interval_scale = tk.Scale(
            interval_row, from_=1, to=30, orient="horizontal",
            length=160, showvalue=0, resolution=1,
            bg=BG, fg=FG, troughcolor=BAR_BG,
            highlightthickness=0, activebackground=MAUVE,
            sliderrelief="flat", command=self._on_interval_change,
        )
        self.interval_scale.set(max(1, min(30, round(self.interval / 1000))))
        self.interval_scale.pack(side="left", padx=6)
        self.interval_value = tk.Label(
            interval_row, text="", font=self.font_mono,
            bg=BG, fg=FG, width=6, anchor="w",
        )
        self.interval_value.pack(side="left")

        # ---- CPU ----
        self.section(container, "CPU")
        tk.Label(
            container, textvariable=self.cpu_total_text, font=self.font_mono,
            bg=BG, fg=FG, anchor="w",
        ).pack(fill="x")
        self.cpu_total_canvas = tk.Canvas(
            container, width=self.bar_width, height=self.bar_height,
            bg=BG, highlightthickness=0,
        )
        self.cpu_total_canvas.pack(anchor="w", pady=(2, 8))

        self.core_frame = tk.Frame(container, bg=BG)
        self.core_frame.pack(pady=(0, 8))
        self.core_canvases = []
        self.core_texts = []

        # ---- 内存 ----
        self.section(container, "内存")
        tk.Label(
            container, textvariable=self.mem_text, font=self.font_mono,
            bg=BG, fg=FG, anchor="w",
        ).pack(fill="x")
        self.mem_canvas = tk.Canvas(
            container, width=self.bar_width, height=self.bar_height,
            bg=BG, highlightthickness=0,
        )
        self.mem_canvas.pack(anchor="w", pady=(2, 4))
        tk.Label(
            container, textvariable=self.swap_text, font=self.font_mono,
            bg=BG, fg=FG, anchor="w",
        ).pack(fill="x")
        self.swap_canvas = tk.Canvas(
            container, width=self.bar_width, height=self.bar_height,
            bg=BG, highlightthickness=0,
        )
        self.swap_canvas.pack(anchor="w", pady=(0, 8))

        # ---- 网络 ----
        self.section(container, "网络")
        self.net_frame = tk.Frame(container, bg=BG)
        self.net_frame.pack(fill="x", pady=(2, 4))
        self.net_labels = {}

        # ---- 采集状态 ----
        prev_cpu_total, prev_cpu_cores = read_cpu_times()
        self.prev_cpu_total = prev_cpu_total
        self.prev_cpu_cores = prev_cpu_cores
        self.prev_net = read_net()
        self.prev_time = time.monotonic()

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(50, self.update_loop)

    def destroy(self):
        """退出前取消挂起的定时器，避免关闭时 Tcl 报错"""
        after_id = getattr(self, "_after_id", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        super().destroy()

    def section(self, parent, name):
        tk.Label(
            parent, text=name, font=self.font_big,
            bg=BG, fg=BLUE, anchor="w",
        ).pack(fill="x")

    def _on_interval_change(self, _value=None):
        """滑动条拖动时实时生效（1 ~ 30 秒）"""
        try:
            val = int(self.interval_scale.get())
        except (ValueError, tk.TclError):
            return
        val = max(1, min(30, val))
        self.interval = val * 1000
        save_config({"interval_sec": val})
        if hasattr(self, "interval_value"):
            self.interval_value.config(text=f"{val} 秒")
        # 立即生效：取消挂起的定时器，尽快按新间隔刷新
        after_id = getattr(self, "_after_id", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
            self._after_id = self.after(50, self.update_loop)

    def draw_bar(self, canvas, pct, color, width=None):
        """在 Canvas 上绘制进度条"""
        canvas.delete("all")
        w = width or self.bar_width
        h = self.bar_height
        canvas.config(width=w)
        canvas.create_rectangle(0, 0, w, h, fill=BAR_BG, outline=BAR_BG)
        fill_w = int(w * max(0.0, min(1.0, pct / 100.0)))
        if fill_w > 0:
            canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline=color)

    def build_core_bars(self, count):
        """按核心数量动态生成每核心进度条（每行 4 个）"""
        for child in self.core_frame.winfo_children():
            child.destroy()
        self.core_canvases = []
        self.core_texts = []
        cols = 4 if count > 4 else count
        for i in range(count):
            r, c = divmod(i, cols)
            cell = tk.Frame(self.core_frame, bg=BG)
            cell.grid(row=r, column=c, padx=(0, 18), sticky="w")
            text = tk.StringVar(value=f"核心{i:02d} --%")
            tk.Label(
                cell, textvariable=text, font=self.font_small,
                bg=BG, fg=FG, anchor="w",
            ).pack(anchor="w")
            canvas = tk.Canvas(
                cell, width=100, height=8,
                bg=BG, highlightthickness=0,
            )
            canvas.pack(anchor="w", pady=(1, 4))
            self.core_canvases.append(canvas)
            self.core_texts.append(text)

    def build_net_rows(self, ifaces):
        """按网卡数量动态生成网速行"""
        for child in self.net_frame.winfo_children():
            child.destroy()
        self.net_labels = {}
        for iface in ifaces:
            row = tk.Frame(self.net_frame, bg=BG)
            row.pack(fill="x", pady=1)
            name = tk.Label(
                row, text=iface, font=self.font_mono, width=8,
                bg=BG, fg=MAUVE, anchor="w",
            )
            name.pack(side="left")
            down = tk.Label(
                row, text="↓ --", font=self.font_mono, width=14,
                bg=BG, fg=GREEN, anchor="w",
            )
            down.pack(side="left")
            up = tk.Label(
                row, text="↑ --", font=self.font_mono, width=14,
                bg=BG, fg=YELLOW, anchor="w",
            )
            up.pack(side="left")
            total = tk.Label(
                row, text="", font=self.font_small,
                bg=BG, fg=SUBTEXT, anchor="w",
            )
            total.pack(side="left")
            self.net_labels[iface] = (down, up, total)

    def update_loop(self):
        if not self.winfo_exists():
            return

        cur_cpu_total, cur_cpu_cores = read_cpu_times()
        cur_net = read_net()
        cur_time = time.monotonic()
        dt = cur_time - self.prev_time

        if dt > 0:
            total_pct = cpu_usage(self.prev_cpu_total, cur_cpu_total)
            core_pcts = [cpu_usage(p, c)
                         for p, c in zip(self.prev_cpu_cores, cur_cpu_cores)]

            # 标题
            self.title_label.config(
                text=f"{time.strftime('%Y-%m-%d %H:%M:%S')}   {read_uptime()}"
            )

            # CPU 总体
            self.cpu_total_text.set(f"总体 {total_pct:5.1f}%")
            self.draw_bar(self.cpu_total_canvas, total_pct, pct_color(total_pct))

            # 每核心（数量变化时重建）
            if len(self.core_canvases) != len(core_pcts):
                self.build_core_bars(len(core_pcts))
            for i, pct in enumerate(core_pcts):
                self.core_texts[i].set(f"核心{i:02d} {pct:5.1f}%")
                self.draw_bar(self.core_canvases[i], pct, pct_color(pct), width=100)

            # 内存
            mem = read_mem()
            self.mem_text.set(
                f"内存 {mem['mem_used']:.0f} / {mem['mem_total']:.0f} MB"
                f"  ({mem['mem_pct']:.1f}%)"
            )
            self.draw_bar(self.mem_canvas, mem["mem_pct"], pct_color(mem["mem_pct"]))
            if mem["swap_total"] > 0:
                self.swap_text.set(
                    f"Swap {mem['swap_used']:.0f} / {mem['swap_total']:.0f} MB"
                    f"  ({mem['swap_pct']:.1f}%)"
                )
                self.draw_bar(self.swap_canvas, mem["swap_pct"],
                              pct_color(mem["swap_pct"]))
            else:
                self.swap_text.set("（无 Swap）")
                self.draw_bar(self.swap_canvas, 0, BAR_BG)

            # 网络
            if list(self.net_labels.keys()) != list(cur_net.keys()):
                self.build_net_rows(list(cur_net.keys()))
            for iface, (rx, tx) in cur_net.items():
                prev_rx, prev_tx = self.prev_net.get(iface, (rx, tx))
                rx_speed = max(0, rx - prev_rx) / dt
                tx_speed = max(0, tx - prev_tx) / dt
                down, up, total = self.net_labels[iface]
                down.config(text=f"↓ {format_speed(rx_speed)}")
                up.config(text=f"↑ {format_speed(tx_speed)}")
                total.config(
                    text=f"累计收 {format_bytes(rx)} / 发 {format_bytes(tx)}"
                )

            self.prev_cpu_total = cur_cpu_total
            self.prev_cpu_cores = cur_cpu_cores
            self.prev_net = cur_net
            self.prev_time = cur_time

        self._after_id = self.after(int(self.interval), self.update_loop)


# ---------------------------------------------------------------
# 入口
# ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ubuntu 桌面实时监控：CPU / 内存 / 网速")
    parser.add_argument("-i", "--interval", type=float, default=1.0,
                        help="刷新间隔（秒，1~30），默认 1.0")
    args = parser.parse_args()

    if not sys.platform.startswith("linux"):
        print("错误：本工具仅支持 Linux（依赖 /proc）", file=sys.stderr)
        sys.exit(1)

    try:
        app = MonitorApp(interval=args.interval)
        app.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
