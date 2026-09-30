# sysmonitor

Ubuntu 桌面实时监控工具（GUI），零第三方依赖（仅 Python 标准库 Tkinter + `/proc`）。

## 功能

- **CPU**：总体使用率 + 每核心使用率进度条（<60% 绿 / <85% 黄 / ≥85% 红）
- **内存**：内存 / Swap 用量与占比
- **网络**：各网卡实时下载（↓）、上传（↑）速度及累计流量
- 系统运行时长、实时时钟

## 使用

```bash
# 默认 1 秒刷新
./sysmonitor.py

# 指定刷新间隔（秒）
./sysmonitor.py -i 0.5
```

## 双击打开

1. 确保文件有执行权限：`chmod +x sysmonitor.py`
2. 文件管理器（Nautilus）双击 `sysmonitor.py` → 选择「运行」（Run）
3. 或安装桌面启动器（推荐，出现在应用菜单中）：

```bash
mkdir -p ~/.local/share/applications
cp sysmonitor.desktop ~/.local/share/applications/
cp sysmonitor.desktop ~/Desktop/ 2>/dev/null || true
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
```

> `sysmonitor.desktop` 中 `Exec` 为绝对路径，如移动项目目录请同步修改。

## 依赖

- Linux（依赖 `/proc` 虚拟文件系统，Ubuntu 20.04+ 测试通过）
- Python 3.8+ 与 `python3-tk`（`sudo apt-get install python3-tk`）
