"""Report structural hotspots without importing or changing application code."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


MAX_LINES = 400
MAX_FILES = 10
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "build", "dist", "logs", "lagrange", "WeatherIcon",
}


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8", errors="surrogateescape")


def inspect_paths(root: Path, names: list[str]) -> dict:
    folders: dict[str, list[str]] = defaultdict(list)
    oversized = []
    unread = []
    file_paths = []
    counted = 0
    text_count = 0
    root = root.resolve()
    for name in sorted(set(names)):
        relative = Path(name)
        if not name or any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in relative.parts):
            continue
        path = root / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        counted += 1
        file_paths.append(relative.as_posix())
        folders[relative.parent.as_posix()].append(relative.name)
        if relative.name == ".env" or (
            relative.name.startswith(".env.") and relative.name != ".env.example"
        ) or relative.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            unread.append({"path": relative.as_posix(), "reason": "sensitive file; contents not read"})
            continue
        try:
            data = path.read_bytes()
            if b"\x00" in data:
                raise UnicodeError("binary")
            content = data.decode("utf-8-sig")
        except (UnicodeError, OSError):
            unread.append({"path": relative.as_posix(), "reason": "binary, non-UTF-8 or unreadable"})
            continue
        text_count += 1
        lines = len(content.splitlines())
        if lines > MAX_LINES:
            oversized.append({"path": relative.as_posix(), "lines": lines})
    return {
        "file_count": counted,
        "file_paths": file_paths,
        "text_file_count": text_count,
        "oversized_files": sorted(oversized, key=lambda item: (-item["lines"], item["path"])),
        "crowded_directories": [
            {"path": folder, "files": len(files), "children": sorted(files)}
            for folder, files in sorted(folders.items()) if len(files) > MAX_FILES
        ],
        "unread_contents": unread,
    }


def scan(root: Path) -> dict:
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    report = inspect_paths(root, names)
    report.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head": git(root, "rev-parse", "HEAD").strip(),
        "limits": {"lines_strictly_greater_than": MAX_LINES, "direct_files_strictly_greater_than": MAX_FILES},
        "scope": "Existing Git-tracked and nonignored untracked files; direct file counts, not recursive; physical UTF-8 lines including comments and blanks. Dependencies, generated directories and symlinks excluded. Binary and sensitive contents not read as text.",
        "working_tree": git(root, "status", "--short", "--untracked-files=all").splitlines(),
    })
    for item in report["oversized_files"]:
        try:
            item["head_lines"] = len(git(root, "show", "HEAD:" + item["path"]).splitlines())
        except subprocess.CalledProcessError:
            item["head_lines"] = None
    return report


def markdown(report: dict) -> str:
    lines = [
        "# 代码结构扫描报告", "", f"扫描时间（UTC）：{report['generated_at']}",
        f"Git HEAD：`{report['head']}`", "",
        "口径：Git 已跟踪文件和未忽略的新文件；检查当前工作区，不代表已提交版本。",
        "统计物理行（包括空行、注释）；目录仅计算直属文件，不计算子目录或递归总量。",
        "严格使用 >400 行、>10 个文件。依赖、构建产物、缓存、符号链接排除；敏感文件不读取正文。",
        "二进制文件计入目录文件数，不参与行数检查。完整清单和跳过原因见 audit.json。", "",
        f"共 {report['file_count']} 个文件，{report['text_file_count']} 个可扫描文本文件。",
        f"发现 {len(report['oversized_files'])} 个大文件、{len(report['crowded_directories'])} 个拥挤目录。", "",
        "## 超过 400 行的文件", "", "| 文件 | 当前行数 | HEAD 行数 |", "| --- | ---: | ---: |",
    ]
    for item in report["oversized_files"]:
        baseline = item["head_lines"] if item["head_lines"] is not None else "未跟踪"
        lines.append(f"| `{item['path']}` | {item['lines']} | {baseline} |")
    lines.extend(["", "## 超过 10 个直属文件的目录", "", "| 目录 | 文件数 |", "| --- | ---: |"])
    for item in report["crowded_directories"]:
        lines.append(f"| `{item['path']}` | {item['files']} |")
    lines.extend([
        "", "## 工作区状态", "",
        f"共有 {len(report['working_tree'])} 条 Git 状态记录；完整状态、文件路径和跳过原因见 [audit.json](audit.json)。",
        "状态清单用于识别未完成工作，不能据此认定改动已验证。", "",
        "报告仅触发通知与方案讨论，不授权 Agent 自动拆分文件、回滚改动或创建远程 PR。", "",
    ])
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write docs/refactor/audit.json and audit.md")
    parser.add_argument("--check", action="store_true", help="Exit 1 when structural hotspots exist")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.write:
        destination = root / "docs" / "refactor"
        destination.mkdir(parents=True, exist_ok=True)
        # Include the report files themselves in the directory-count snapshot.
        for name in ("audit.json", "audit.md"):
            (destination / name).touch(exist_ok=True)
    report = scan(root)
    if args.write:
        # Compact JSON keeps a machine-generated report from becoming a line-count hotspot.
        (destination / "audit.json").write_text(json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8")
        (destination / "audit.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return int(args.check and bool(report["oversized_files"] or report["crowded_directories"]))


if __name__ == "__main__":
    raise SystemExit(main())
