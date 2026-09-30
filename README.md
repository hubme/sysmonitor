# sysmonitor

Ubuntu 终端实时监控工具，零第三方依赖（仅使用 Python 标准库，直接读取 `/proc`）。

## 功能

- **CPU**：总体使用率 + 每核心使用率（柱状图）
- **内存**：内存 / Swap 用量与占比
- **网络**：各网卡实时上传、下载速度及累计流量
- 系统运行时长、实时时钟

## 使用

```bash
# 默认 1 秒刷新
python3 sysmonitor.py

# 指定刷新间隔（秒）
python3 sysmonitor.py -i 0.5
```

建议直接安装为命令：

```bash
sudo install -m 755 sysmonitor.py /usr/local/bin/sysmonitor
```

## 按键

| 按键 | 功能 |
|------|------|
| `q` | 退出 |
| `+` / `-` | 调整刷新间隔（0.2 ~ 5 秒） |
| 窗口缩放 | 自适应重新布局 |

## 环境

- Linux（依赖 `/proc` 虚拟文件系统，Ubuntu 20.04+ 测试通过）
- Python 3.8+
- 终端需支持 curses（任意常规终端均可）
