"""Image and speech adapters, including deferred temporary-file tracking."""
from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, List

from nonebot.adapters.onebot.v11 import MessageSegment

from src.services.tools.intent import IntentDecision

from .dependencies import ToolDependencies
from .models import ToolExecutionResult

logger = logging.getLogger(__name__)


@contextmanager
def _media_file(
    payload: bytes, suffix: str, track_temp_file: Callable[[Path], None],
    temporary_files=None,
) -> Iterator[Path]:
    resource = temporary_files.reserve() if temporary_files is not None else None
    try:
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    except BaseException:
        if resource is not None:
            temporary_files.manager.discard_uncreated(resource)
        raise
    path = Path(f.name)
    try:
        if resource is not None:
            temporary_files.bind(resource, path, f)
        track_temp_file(path)
        f.write(payload)
        f.close()
        yield path
    except BaseException:
        if resource is not None:
            try:
                temporary_files.manager.try_cleanup(resource)
            except Exception:
                logger.warning("Media cleanup failed; resource retained for sender cleanup")
            raise
        # Preserve the primary error (including cancellation) if cleanup fails.
        # Windows cannot unlink an open file; keep its tracked path for retry.
        try:
            if not f.closed:
                f.close()
        except OSError:
            logger.warning("Media file close failed during error cleanup")
        if f.closed:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # Still tracked: the sender's cleanup can retry.
        raise


async def handle(
    decision: IntentDecision, result: ToolExecutionResult, text: str,
    image_urls: List[str], audio_urls: List[str], *,
    track_temp_file: Callable[[Path], None], dependencies: ToolDependencies,
    temporary_files=None,
) -> bool:
    name = decision.name
    args = decision.args

    if name == "image.describe":
        desc = await dependencies.describe_image_url(image_urls[0])
        result.fact_lines.append(f"图片理解结果: {desc}")
        return True

    if name == "image.generate":
        prompt = args.get("prompt") or text
        url = await dependencies.generate_image(prompt)
        result.fact_lines.append(f"图片生成完成，提示词: {prompt}")
        result.extra_messages.append(MessageSegment.image(file=url))
        return True

    if name == "image.process":
        raw = await dependencies.download_image_bytes(image_urls[0])
        out = await dependencies.process_image(raw, args.get("operation", "grayscale"), args.get("value") or None)
        if not out:
            result.diagnostic_lines.append("图片处理失败: 输入图片无效。")
            return False
        suffix = ".png" if out.startswith(b"\x89PNG") else ".jpg"
        with _media_file(out, suffix, track_temp_file, temporary_files) as path:
            message = MessageSegment.image(file=str(path))
            result.fact_lines.append(
                f"图片处理完成，操作={args.get('operation')} 参数={args.get('value', '')}".strip()
            )
            result.extra_messages.append(message)
        return True

    if name == "language.tts":
        audio = await dependencies.text_to_speech(args.get("text", text))
        with _media_file(audio, ".mp3", track_temp_file, temporary_files) as path:
            message = MessageSegment.record(file=str(path))
            result.fact_lines.append("已将文本转换成语音。")
            result.extra_messages.append(message)
        return True

    if name == "language.stt":
        audio = await dependencies.download_image_bytes(audio_urls[0])
        transcript = await dependencies.speech_to_text(audio, filename="audio.mp3")
        result.fact_lines.append(f"语音识别结果: {transcript}")
        return True

    return False
