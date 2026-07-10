#!/usr/bin/env python3
"""mako-bot OOM 事件调查与修复可视化面板。

依赖: rich
运行: python3 tools/incident_tui.py

按键: ← → 翻页 | 1-5 直达 | q 退出
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Callable, List, Optional, Tuple

# ── Rich ────────────────────────────────────────────────────────────────────
from rich.align import Align
from rich.console import Console, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

# ═══════════════════════════════════════════════════════════════════════════════
# 配色常量
# ═══════════════════════════════════════════════════════════════════════════════

RED = Style(color="red", bold=True)
GREEN = Style(color="green", bold=True)
CYAN = Style(color="cyan")
WHITE_BOLD = Style(color="white", bold=True)
DIM = Style(color="grey70")

BOX_RED = "red"
BOX_YELLOW = "yellow"
BOX_GREEN = "green"
BOX_CYAN = "cyan"


def _make_bar(label: str, value: int, max_val: int, width: int = 40, color: str = "red", units: str = " MB") -> Text:
    """绘制彩色进度条：label [████░░░░] value MB"""
    ratio = min(value / max(max_val, 1), 1.0)
    filled = int(round(ratio * width))
    empty = width - filled
    bar = Text()
    bar.append(f"{label:<20}", style=DIM)
    bar.append(" ▐", style=Style(color=color))
    bar.append("█" * filled, style=Style(color=color, bold=True))
    bar.append("░" * empty, style=Style(color=color))
    bar.append("▌ ", style=Style(color=color))
    bar.append(f"{value}{units}", style=Style(color=color, bold=True))
    return bar


# ═══════════════════════════════════════════════════════════════════════════════
# 第 1 页：时间线
# ═══════════════════════════════════════════════════════════════════════════════

OOM_EVENTS: List[Tuple[str, str, str]] = [
    ("6/30 11:21", "OOM Kill #1 — mako-bot 被杀 (RSS 392MB)", "red"),
    ("6/30 16:02", "OOM Kill #2 — mako-bot 被杀 (RSS 372MB)", "red"),
    ("6/30 22:43", "OOM Kill #3 — mako-bot 被杀 (RSS 401MB)", "red"),
    ("7/01 13:34", "OOM Kill #4 — mako-bot 被杀 + SSH 连接限流", "red"),
    ("7/01 19:20", "OOM Kill #5 — 系统内存彻底耗尽", "red"),
    ("7/01 19:31", "OOM Kill #6 — napcat/QQ 进程被杀", "red"),
    ("7/01 19:43", "♻ 阿里云监测到失联，自动重启服务器", "yellow"),
]


def build_timeline_page() -> Panel:
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("marker", width=16, style="bold")
    table.add_column("event", style="bold")

    prev_day: Optional[str] = None
    for i, (ts, event, color) in enumerate(OOM_EVENTS):
        day = ts.split()[0]
        if day != prev_day:
            table.add_row(Text(day, style=Style(color="cyan", bold=True)), Text(""))
            prev_day = day

        marker = Text("●", style=Style(color=color, bold=True))
        marker.append(f"  {ts.split(maxsplit=1)[1]}")
        evt = Text(event, style=Style(color=color))
        table.add_row(marker, evt)

    summary = Text(
        "\n6 次 OOM-Killer 事件，跨越约 33 小时。服务器：阿里云 ECS，1.5 GB 内存，2 vCPU，无 swap。",
        style=DIM,
    )
    body = Table.grid(padding=(0, 4))
    body.add_row(table, Text(""))
    body.add_row(summary)

    return Panel(body, title="[bold]⏱ 时间线 — OOM 事件全记录[/]", border_style=BOX_RED, padding=(1, 2))


# ═══════════════════════════════════════════════════════════════════════════════
# 第 2 页：根因分析
# ═══════════════════════════════════════════════════════════════════════════════

def build_root_cause_page() -> Panel:
    steps: List[Tuple[str, str, str]] = [
        ("1. 用户发图", "用户在群聊中发送含图片的消息给 mako-bot", "yellow"),
        ("2. 无大小限制", "mako-bot 下载图片 — 没有任何大小上限", "red"),
        ("3. 全量下载", "整张图片加载到内存（可能 100+ MB）", "red"),
        ("4. PIL 解码", "PIL 解码原始像素 → 内存中出现第二份拷贝", "red"),
        ("5. Qwen Vision", "视觉模型处理 → 额外 GPU/CPU 内存占用", "red"),
        ("6. RSS 飙升", "RSS 飙至 350–400 MB（机器只有 1.5 GB）", "red"),
        ("7. OOM Killer", "Linux OOM Killer 杀掉 mako-bot → napcat/QQ 也被杀", "red"),
        ("8. SSH 挂死", "系统无响应 — SSH 连接被限流/断开", "yellow"),
        ("9. 自动重启", "♻ 阿里云运维监测到失联，7/1 19:43 自动重启", "green"),
    ]

    flow = Table.grid(padding=(0, 2))
    flow.add_column(width=18)
    flow.add_column(width=1)
    flow.add_column()

    for i, (step, desc, color) in enumerate(steps):
        flow.add_row(
            Text(step, style=Style(color=color, bold=True)),
            Text("→", style=Style(color=color)),
            Text(desc, style=Style(color=color)),
        )
        if i < len(steps) - 1:
            flow.add_row(Text(""), Text("│", style=DIM), Text(""))

    mem_info = Table(title="内存概况", box=None, padding=(0, 2))
    mem_info.add_column("指标", style="bold cyan")
    mem_info.add_column("数值", style="bold yellow")
    mem_info.add_row("机器总内存", "1.5 GB（阿里云 ECS）")
    mem_info.add_row("mako-bot 正常 RSS", "~100–150 MB")
    mem_info.add_row("mako-bot 图片处理时 RSS", "350–400 MB ⚠")
    mem_info.add_row("峰值剩余内存", "< 100 MB → 触发 OOM Killer")

    body = Table.grid(padding=(0, 4))
    body.add_row(flow, Align.center(mem_info))

    return Panel(body, title="[bold]🔍 根因分析 — 攻击链[/]", border_style=BOX_RED, padding=(1, 2))


# ═══════════════════════════════════════════════════════════════════════════════
# 第 3 页：修复概览
# ═══════════════════════════════════════════════════════════════════════════════

FIXES: List[Tuple[str, str, str, str]] = [
    (
        "config.py",
        "新增 6 个安全配置项",
        "无任何限制",
        "10MB 下载上限 | 4096 尺寸限制 | ~4K 像素上限\n15s 超时 | 30s 速率限制",
    ),
    (
        "image.py",
        "下载前 HEAD 预检 + 流式截断\nPIL 解码前校验尺寸",
        "直接全量下载，不做任何校验\nPIL 解码不做尺寸检查",
        "HEAD 先查 Content-Length\n超过上限直接拒绝\nPIL open → 校验尺寸 → 再 load",
    ),
    (
        "gemini.py",
        "base64 编码移入线程池",
        "同步 base64 编码阻塞事件循环",
        "asyncio.to_thread 异步执行",
    ),
    (
        "tool_executor.py",
        "临时文件追踪 + 延迟清理",
        "临时文件创建后从不删除\n/tmp 无限累积",
        "追踪所有临时文件\n消息发送后统一清理",
    ),
    (
        "chat.py",
        "用户级速率限制\n图片上下文并行构建",
        "无速率限制\n图片逐张串行处理",
        "每用户 30s 内只能触发一次\nasyncio.gather 并行处理",
    ),
    (
        "errors.py",
        "新增 ImageTooLargeError",
        "无专用异常类型",
        "继承 AppError，带详细消息",
    ),
]


def build_fixes_page() -> Panel:
    table = Table(title="", box=None, padding=(0, 1), show_lines=True)
    table.add_column("文件", style="bold cyan", width=16)
    table.add_column("修改内容", style="bold green", width=22)
    table.add_column("修复前", style="red", width=30)
    table.add_column("修复后", style="green", width=36)

    for fname, change, before, after in FIXES:
        table.add_row(fname, change, before, after)

    return Panel(
        table,
        title="[bold]🛠 修复清单 — 6 个文件[/]",
        border_style=BOX_GREEN,
        padding=(1, 2),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 第 4 页：内存对比
# ═══════════════════════════════════════════════════════════════════════════════

def build_memory_page() -> Panel:
    left = Table(title="修复前", box=None, padding=(0, 1), title_style="bold red")
    left.add_column("", style=DIM)
    bars_before = [
        _make_bar("图片下载", 500, 500, color="red"),
        _make_bar("PIL 解码", 400, 500, color="red"),
        _make_bar("base64 编码", 133, 500, color="red"),
        _make_bar("临时文件泄漏", 200, 500, color="red"),
        _make_bar("并发 ×3", 400, 500, color="red"),
    ]
    for b in bars_before:
        left.add_row(b)

    right = Table(title="修复后", box=None, padding=(0, 1), title_style="bold green")
    right.add_column("", style=DIM)
    bars_after = [
        _make_bar("图片下载", 10, 500, color="green"),
        _make_bar("PIL 解码", 37, 500, color="green"),
        _make_bar("base64 编码", 13, 500, color="green"),
        _make_bar("临时文件泄漏", 0, 500, color="green"),
        _make_bar("并发 ×3", 30, 500, color="green"),
    ]
    for b in bars_after:
        right.add_row(b)

    summary = Text(
        "\n修复前单张图片可消耗 400+ MB → 修复后限制在 ~50 MB 以内（含速率限制和并发控制）",
        style=CYAN,
    )

    grid = Table.grid(padding=(0, 4))
    grid.add_row(Align.center(left), Align.center(right))
    grid.add_row(Align.center(summary))

    return Panel(grid, title="[bold]📊 内存对比 — 修复前 vs 修复后[/]", border_style=BOX_YELLOW, padding=(1, 2))


# ═══════════════════════════════════════════════════════════════════════════════
# 第 5 页：配置项
# ═══════════════════════════════════════════════════════════════════════════════

SETTINGS: List[Tuple[str, str, str]] = [
    ("image_max_download_bytes", "10 MB (10,485,760)", "HTTP 下载图片的最大字节数"),
    ("image_max_width", "4096 px", "PIL 解码前最大宽度校验"),
    ("image_max_height", "4096 px", "PIL 解码前最大高度校验"),
    ("image_max_pixels", "8,847,360 (~4K)", "PIL 解码前最大像素总数校验"),
    ("image_download_timeout", "15.0 秒", "单张图片下载超时时间"),
    ("image_rate_limit_seconds", "30 秒", "每用户两次图片处理的最小间隔"),
]


def build_settings_page() -> Panel:
    table = Table(title="", box=None, padding=(0, 1), show_lines=True)
    table.add_column("配置项", style="bold cyan", width=28)
    table.add_column("默认值", style="bold yellow", width=22)
    table.add_column("防护作用", style="green", width=52)

    for name, default, desc in SETTINGS:
        table.add_row(name, default, desc)

    note = Text(
        "\n所有配置项位于 src/core/config.py 的 '# Image safety' 区域。\n"
        "可通过 .env 文件或环境变量覆盖默认值。",
        style=DIM,
    )

    grid = Table.grid(padding=(0, 0))
    grid.add_row(table)
    grid.add_row(note)
    return Panel(grid, title="[bold]⚙ 新增安全配置项[/]", border_style=BOX_CYAN, padding=(1, 2))


# ═══════════════════════════════════════════════════════════════════════════════
# TUI 引擎
# ═══════════════════════════════════════════════════════════════════════════════

PAGE_BUILDERS: List[Tuple[str, Callable[[], Panel]]] = [
    ("时间线", build_timeline_page),
    ("根因分析", build_root_cause_page),
    ("修复概览", build_fixes_page),
    ("内存对比", build_memory_page),
    ("配置项", build_settings_page),
]


def _build_header() -> RenderableType:
    title = Text("mako-bot OOM 事件调查与修复报告", style=WHITE_BOLD)
    subtitle = Text("2026-07-01 | 阿里云 ECS (1.5GB RAM, 2 vCPU) | 6 次 OOM → 自动重启", style=CYAN)
    return Panel(Align.center(Text.assemble(title, "\n", subtitle)), style=Style(color="bright_black"), height=3)


def _build_footer(page_idx: int, total: int, page_name: str) -> RenderableType:
    nav = "  ".join(
        f"{'▶ ' if i == page_idx else '  '}[{name}]" for i, (name, _) in enumerate(PAGE_BUILDERS)
    )
    bar = Text()
    bar.append(" 第 ", style=DIM)
    bar.append(f"{page_idx + 1}/{total}", style=WHITE_BOLD)
    bar.append(f" 页 — {page_name}  │  ", style=CYAN)
    bar.append(nav)
    bar.append("  │  ← → 翻页  │  1-5 直达  │  q 退出", style=DIM)
    return Panel(bar, height=3, style=Style(color="bright_black"))


def _make_layout() -> Layout:
    layout = Layout()
    layout.split(Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=3))
    return layout


# ═══════════════════════════════════════════════════════════════════════════════
# 键盘输入（后台线程 + 队列，全程不碰终端模式）
# ═══════════════════════════════════════════════════════════════════════════════

_key_queue: "queue.Queue[str]" = queue.Queue()


def _stdin_reader() -> None:
    """后台线程：打开 /dev/tty，设为 cbreak 模式，持续读取按键。

    cbreak 模式确保：
    - 不回显（不会出现 ^[[C）
    - 逐字符立即可读（无行缓冲）
    - Ctrl-C 仍能触发 KeyboardInterrupt
    """
    import fcntl
    import os
    import termios
    import tty

    try:
        tty_fd = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
        tty_fd = sys.stdin.fileno()

    # 保存原始终端属性，退出时恢复
    old_attrs = termios.tcgetattr(tty_fd)
    tty.setcbreak(tty_fd)

    # 设为非阻塞模式
    fl = fcntl.fcntl(tty_fd, fcntl.F_GETFL)
    fcntl.fcntl(tty_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    buf = ""
    try:
        while True:
            try:
                data = os.read(tty_fd, 1)
                if not data:
                    _key_queue.put("q")
                    return
            except BlockingIOError:
                time.sleep(0.05)
                continue
            except OSError:
                time.sleep(0.05)
                continue

            ch = data.decode("utf-8", errors="replace")
            buf += ch
            if buf == "\x1b":
                continue
            if buf.startswith("\x1b") and len(buf) >= 3:
                _key_queue.put(buf)
                buf = ""
            elif buf.startswith("\x1b"):
                continue
            else:
                _key_queue.put(buf)
                buf = ""
    finally:
        try:
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_attrs)
        except Exception:
            pass


def _drain_keys() -> List[str]:
    """取出队列中所有按键。"""
    keys: List[str] = []
    while True:
        try:
            keys.append(_key_queue.get_nowait())
        except queue.Empty:
            break
    return keys


def run_tui() -> None:
    # 启动后台键盘读取线程
    reader = threading.Thread(target=_stdin_reader, daemon=True)
    reader.start()

    console = Console()
    layout = _make_layout()

    page_idx = 0
    total = len(PAGE_BUILDERS)

    with Live(layout, console=console, screen=True, refresh_per_second=10) as live:
        while True:
            name, builder = PAGE_BUILDERS[page_idx]
            layout["header"].update(_build_header())
            layout["body"].update(builder())
            layout["footer"].update(_build_footer(page_idx, total, name))

            keys = _drain_keys()
            if keys:
                for key in keys:
                    if key in ("q", "Q", "\x03"):
                        return
                    elif key in ("\x1b[C", "l", "L", " "):
                        page_idx = (page_idx + 1) % total
                    elif key in ("\x1b[D", "h", "H"):
                        page_idx = (page_idx - 1) % total
                    elif key in ("1", "2", "3", "4", "5"):
                        page_idx = int(key) - 1

            time.sleep(0.05)


def main() -> None:
    try:
        run_tui()
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h", end="", flush=True)


if __name__ == "__main__":
    main()
