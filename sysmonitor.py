#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sysmonitor —— Ubuntu 终端实时监控工具

实时显示：
  - CPU 总体使用率及每核心使用率（柱状图）
  - 内存 / Swap 使用情况
  - 上传、下载网速（含累计流量）

零第三方依赖，直接读取 /proc 虚拟文件系统。
"""

import argparse
import curses
import os

import sys
import time


# ---------------------------------------------------------------
# 数据采集层
# ---------------------------------------------------------------

def read_cpu_times():
    """读取 /proc/stat，返回 (总体时间列表, [每核心时间列表])"""
    cpus = {}
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu"):
                parts = line.split()
                name = parts[0]
                values = [int(x) for x in parts[1:]]
                cpus[name] = values
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
            num = val.strip().split()[0]
            info[key] = int(num) / 1024.0  # kB -> MB

    mem_total = info.get("MemTotal", 0.0)
    mem_avail = info.get("MemAvailable", info.get("MemFree", 0.0))
    mem_used = mem_total - mem_avail
    swap_total = info.get("SwapTotal", 0.0)
    swap_free = info.get("SwapFree", 0.0)
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
        rx, tx = int(fields[0]), int(fields[8])
        if iface == "lo":
            continue
        stats[iface] = (rx, tx)
    return stats


def format_speed(bps):
    """字节/秒 -> 人类可读"""
    if bps < 1024:
        return f"{bps:6.0f} B/s"
    for unit in ("KB/s", "MB/s", "GB/s"):
        bps /= 1024.0
        if bps < 1024:
            return f"{bps:6.2f} {unit}"
    return f"{bps:6.2f} TB/s"


def format_bytes(b):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


def bar(pct, width, filled="#", empty="-"):
    n = int(pct / 100.0 * width)
    n = max(0, min(width, n))
    return filled * n + empty * (width - n)


# ---------------------------------------------------------------
# 界面层
# ---------------------------------------------------------------

def draw(stdscr, snapshot):
    h, w = stdscr.getmaxyx()
    row = 0

    def put(y, x, text, attr=0):
        if y < h - 1 and x < w - 1:
            try:
                stdscr.addnstr(y, x, text, w - x - 1, attr)
            except curses.error:
                pass

    title = f" sysmonitor  |  {time.strftime('%Y-%m-%d %H:%M:%S')}  |  {snapshot['uptime']} "
    put(row, 0, title.ljust(w)[:w], curses.A_REVERSE)
    row += 2

    # ---- CPU ----
    put(row, 2, "CPU", curses.A_BOLD)
    row += 1
    total_pct = snapshot["cpu_total"]
    put(row, 4, f"总体: {total_pct:5.1f}%  [{bar(total_pct, max(10, w - 30))}]")
    row += 2

    # 每核心，两列排布
    core_w = max(10, (w - 20) // 2)
    for i, pct in enumerate(snapshot["cpu_cores"]):
        col = 4 if i % 2 == 0 else 4 + core_w
        put(row, col, f"核心{i:02d} {pct:5.1f}% [{bar(pct, core_w - 20)}]")
        if i % 2 == 1:
            row += 1
    row += 2

    # ---- 内存 ----
    mem = snapshot["mem"]
    put(row, 2, "内存", curses.A_BOLD)
    row += 1
    put(row, 4, (
        f"已用 {mem['mem_used']:8.0f} MB / {mem['mem_total']:8.0f} MB "
        f"[{mem['mem_pct']:5.1f}%] [{bar(mem['mem_pct'], max(10, w - 60))}]"
    ))
    row += 1
    if mem["swap_total"] > 0:
        put(row, 4, (
            f"Swap {mem['swap_used']:8.0f} MB / {mem['swap_total']:8.0f} MB "
            f"[{mem['swap_pct']:5.1f}%] [{bar(mem['swap_pct'], max(10, w - 60))}]"
        ))
        row += 1
    row += 1

    # ---- 网络 ----
    put(row, 2, "网络", curses.A_BOLD)
    row += 1
    if not snapshot["net"]:
        put(row, 4, "未检测到网卡")
        row += 1
    for iface, info in snapshot["net"].items():
        color = curses.color_pair(3)
        put(row, 4, f"{iface[:10]:<10} ↓下载 {format_speed(info['rx_speed']):>12}   ↑上传 {format_speed(info['tx_speed']):>12}", color)
        put(row + 1, 4, f"{'':<10} 累计收 {format_bytes(info['rx_total']):>12}   累计发 {format_bytes(info['tx_total']):>12}")
        row += 2
    row += 1

    put(h - 1, 0, " q: 退出  +/-: 调整刷新间隔  ".ljust(w)[:w], curses.A_REVERSE)


def read_uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
    except (OSError, ValueError):
        return ""
    days, rem = divmod(int(secs), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"运行 {days}天{hours}时{minutes}分"


# ---------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------

def run(stdscr, interval):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)

    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_CYAN, -1)
    except curses.error:
        pass

    prev_cpu_total, prev_cpu_cores = read_cpu_times()
    prev_net = read_net()
    prev_time = time.monotonic()

    while True:
        time.sleep(interval)

        cur_cpu_total, cur_cpu_cores = read_cpu_times()
        cur_net = read_net()
        cur_time = time.monotonic()
        dt = cur_time - prev_time
        if dt <= 0:
            continue

        snapshot = {
            "uptime": read_uptime(),
            "cpu_total": cpu_usage(prev_cpu_total, cur_cpu_total),
            "cpu_cores": [cpu_usage(p, c) for p, c in zip(prev_cpu_cores, cur_cpu_cores)],
            "mem": read_mem(),
            "net": {},
        }

        for iface, (rx, tx) in cur_net.items():
            prev_rx, prev_tx = prev_net.get(iface, (rx, tx))
            snapshot["net"][iface] = {
                "rx_speed": max(0, rx - prev_rx) / dt,
                "tx_speed": max(0, tx - prev_tx) / dt,
                "rx_total": rx,
                "tx_total": tx,
            }

        stdscr.erase()
        draw(stdscr, snapshot)
        stdscr.refresh()

        # 处理按键
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            return
        elif key in (ord("+"), ord("=")):
            interval = min(5.0, interval + 0.2)
        elif key in (ord("-"), ord("_")):
            interval = max(0.2, interval - 0.2)

        prev_cpu_total, prev_cpu_cores = cur_cpu_total, cur_cpu_cores
        prev_net = cur_net
        prev_time = cur_time


def main():
    parser = argparse.ArgumentParser(description="Ubuntu 终端实时监控：CPU / 内存 / 网速")
    parser.add_argument("-i", "--interval", type=float, default=1.0,
                        help="刷新间隔（秒），默认 1.0")
    args = parser.parse_args()

    if not sys.platform.startswith("linux"):
        print("错误：本工具仅支持 Linux（依赖 /proc）", file=sys.stderr)
        sys.exit(1)

    try:
        curses.wrapper(run, args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
