"""Private image files, bounded background capture, and daily vision inputs."""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from nonebot.log import logger

from src.core.config import get_settings
from src.services.integrations.image import download_image_data
from src.services.integrations.vision_input import inline_image, validated_image_mime


MAX_MEMORY_IMAGES = 3


class MemoryImageArchive:
    def __init__(self, root=None, *, capacity=64, download=download_image_data):
        self.root = Path(root or Path(__file__).resolve().parents[3] / "data/memory_images").resolve()
        self.capacity, self.download = capacity, download
        self._pending: dict[str, asyncio.Task] = {}
        self._semaphore: asyncio.Semaphore | None = None

    @staticmethod
    def key(url):
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def _path(self, url):
        path = self.root / (self.key(url) + ".img")
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError("invalid image archive path")
        return path

    def _save(self, url, content):
        validated_image_mime(content)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Keep room for the bot, Redis and logs even when group traffic is high.
        if shutil.disk_usage(self.root).free < len(content) + 256 * 1024 * 1024:
            raise OSError("image archive disk reserve reached")
        path = self._path(url)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=path.stem + "-",
                                             suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                os.chmod(temporary, 0o600)
                stream.write(content)
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                if temporary.resolve().parent == self.root:
                    temporary.unlink()

    async def _capture(self, url):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(1)
        async with self._semaphore:
            try:
                path = self._path(url)
                if path.is_file():
                    os.utime(path, None)
                    return True
                content, _mime = await self.download(url)
                await asyncio.to_thread(self._save, url, content)
                return True
            except Exception as exc:
                logger.warning("记忆图片保存失败 error_type={}", type(exc).__name__)
                return False

    def enqueue(self, urls):
        """Do not hold chat receipt/reply handling while images download."""
        for url in dict.fromkeys(urls[:MAX_MEMORY_IMAGES]):
            key = self.key(url)
            if key in self._pending:
                continue
            if len(self._pending) >= self.capacity:
                logger.warning("记忆图片下载队列已满，保留引用供每日整理补取")
                break
            task = asyncio.create_task(self._capture(url))
            self._pending[key] = task
            task.add_done_callback(lambda _task, key=key: self._pending.pop(key, None))

    def _read_inline(self, url):
        path = self._path(url)
        if path.stat().st_size > get_settings().image_max_download_bytes:
            raise ValueError("archived image exceeds download limit")
        return inline_image(path.read_bytes())

    async def load(self, url):
        try:
            key = self.key(url)
            pending = self._pending.get(key)
            if pending is not None:
                await asyncio.shield(pending)
            elif not self._path(url).is_file():
                # Redis keeps the reference, so interrupted/backlogged capture can recover.
                if not await self._capture(url):
                    return None
            return await asyncio.to_thread(self._read_inline, url)
        except Exception as exc:
            logger.warning("记忆图片读取失败 error_type={}", type(exc).__name__)
            return None

    async def close(self):
        tasks = list(self._pending.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def prune(self, retained_urls):
        """Remove only old owned files no longer referenced by retained raw history."""
        if not self.root.is_dir():
            return
        retained = {self.key(url) for url in retained_urls}
        cutoff = time.time() - 3600
        for path in self.root.iterdir():
            if (path.is_symlink() or path.resolve().parent != self.root
                    or not re.fullmatch(r"[0-9a-f]{64}\.img", path.name)):
                continue
            if (path.stem not in retained and path.stem not in self._pending
                    and path.stat().st_mtime < cutoff):
                path.unlink()


@lru_cache(maxsize=1)
def get_image_archive():
    return MemoryImageArchive()


async def memory_model_content(prompt, records, archive, *, vision_enabled):
    parts = [{"type": "text", "text": prompt}]
    attached = 0
    for record in records:
        for position, url in enumerate(record.image_urls[:MAX_MEMORY_IMAGES], 1):
            scene = f"群 {record.group_id}" if record.group_id else "私聊"
            label = f"{scene}，发送者 {record.user_id}，时间 {record.time.isoformat()}，第 {position} 张图"
            data = await archive.load(url) if vision_enabled and attached < MAX_MEMORY_IMAGES else None
            parts.append({"type": "text", "text": "\n图片上下文：" + label})
            if data:
                parts.append({"type": "image_url", "image_url": {"url": data}})
                attached += 1
            else:
                parts.append({"type": "text", "text": "图片内容未附加，不得推测图中信息。"})
    return parts if len(parts) > 1 else prompt
