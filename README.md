# sysmonitor

Ubuntu 桌面实时监控工具（GUI），零第三方依赖（仅 Python 标准库 Tkinter + `/proc`）。

## 功能

- **CPU**：总体使用率 + 每核心使用率进度条（<60% 绿 / <85% 黄 / ≥85% 红）
- **内存**：内存 / Swap 用量与占比
- **网络**：各网卡实时下载（↓）、上传（↑）速度及累计流量
- 系统运行时长、实时时钟

## 使用

```bash
# 方式一：独立可执行文件（已打包，无需安装 Python/Tkinter，双击即可）
./dist/sysmonitor

# 方式二：源码运行
./sysmonitor.py          # 默认 1 秒刷新
./sysmonitor.py -i 0.5   # 指定刷新间隔（秒）
```

## 打包独立应用

使用 PyInstaller 打包为单文件可执行程序：

```bash
python3 -m pip install --user pyinstaller
~/.local/bin/pyinstaller --onefile --windowed --name sysmonitor \
    --distpath dist --workpath build --specpath build sysmonitor.py
```

产物：`dist/sysmonitor`（约 11MB），拷贝到任意同架构 Ubuntu 机器均可直接运行。

## 双击打开

1. 确保文件有执行权限：`chmod +x sysmonitor.py`
2. 文件管理器（Nautilus）双击 `sysmonitor.py` → 选择「运行」（Run）
3. 或安装桌面启动器（推荐，指向已打包的 `dist/sysmonitor`，出现在应用菜单中）：

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
