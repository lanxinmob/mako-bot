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
        "# Structure audit", "", f"Generated (UTC): {report['generated_at']}",
        f"HEAD: `{report['head']}`", "",
        "Scope: tracked and nonignored working-tree files; physical lines and direct files only.",
        "Limits: >400 lines or >10 direct files. Dependencies, caches and symlinks are excluded.",
        "Binary files count toward directory limits; sensitive contents are not read.", "",
        f"Files: {report['file_count']} ({report['text_file_count']} text).",
        f"Hotspots: {len(report['oversized_files'])} files, {len(report['crowded_directories'])} directories.", "",
        "## Oversized files", "", "| File | Lines | HEAD lines |", "| --- | ---: | ---: |",
    ]
    for item in report["oversized_files"]:
        baseline = item["head_lines"] if item["head_lines"] is not None else "untracked"
        lines.append(f"| `{item['path']}` | {item['lines']} | {baseline} |")
    lines.extend(["", "## Crowded directories", "", "| Directory | Files |", "| --- | ---: |"])
    for item in report["crowded_directories"]:
        lines.append(f"| `{item['path']}` | {item['files']} |")
    lines.extend([
        "", f"Working-tree changes: {len(report['working_tree'])}.",
        "With --write, audit.json contains the full inventory and exclusions.",
        "Hotspots require a developer-approved refactor plan.", "",
    ])
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write .reports/structure/audit.json and audit.md")
    parser.add_argument("--check", action="store_true", help="Exit 1 when structural hotspots exist")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.write:
        destination = root / ".reports" / "structure"
        destination.mkdir(parents=True, exist_ok=True)
    report = scan(root)
    if args.write:
        # Compact JSON keeps a machine-generated report from becoming a line-count hotspot.
        (destination / "audit.json").write_text(json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8")
        (destination / "audit.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return int(args.check and bool(report["oversized_files"] or report["crowded_directories"]))


if __name__ == "__main__":
    raise SystemExit(main())
