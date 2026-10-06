"""Image admission and enriched chat input composition."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import (
    Awaitable,
    Callable,
    List,
    Optional,
)
from src.services.integrations.image import describe_image_url
from src.services.integrations.vision_input import native_vision_enabled, prepare_native_image
from src.services.retrieval import dependencies
from src.services.retrieval.context import SearchContextBuilder
from src.services.retrieval.models import SearchOutcome
from src.services.retrieval.formatting import MAX_IMAGES_TO_DESCRIBE

@dataclass(frozen=True)
class EnrichedChatInput:
    user_text: str
    llm_text: str
    image_context: str = ""
    search_context: str = ""
    search_outcome: SearchOutcome = field(default_factory=SearchOutcome)
    image_inputs: List[str] = field(default_factory=list)


class ImageRateLimiter:
    def __init__(self, interval_seconds: Optional[int] = None, *, dependencies=dependencies) -> None:
        self._deps = dependencies
        self.interval_seconds = (
            self._deps.get_settings().image_rate_limit_seconds
            if interval_seconds is None
            else interval_seconds
        )
        self._last_seen: dict[int, float] = {}

    def allow(self, user_id: int, *, now: Optional[float] = None) -> bool:
        current = self._deps.time.time() if now is None else now
        last = self._last_seen.get(user_id, 0.0)
        if current - last < self.interval_seconds:
            return False
        self._last_seen[user_id] = current
        return True


class ChatContextBuilder:
    def __init__(
        self,
        *,
        dependencies=dependencies,
        search_builder: Optional[SearchContextBuilder] = None,
        image_limiter: Optional[ImageRateLimiter] = None,
        describe: Callable[[str], Awaitable[str]] = describe_image_url,
        prepare: Callable[[str], Awaitable[str]] = prepare_native_image,
        native_vision: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._deps = dependencies
        self.search_builder = search_builder or SearchContextBuilder(dependencies=dependencies)
        self.image_limiter = image_limiter or ImageRateLimiter(dependencies=dependencies)
        self.describe = describe
        self.prepare = prepare
        self.native_vision = native_vision or (lambda: native_vision_enabled(self._deps.get_settings()))

    async def build(
        self,
        *,
        user_id: int,
        user_text: str,
        image_urls: List[str],
        history: List[dict],
    ) -> EnrichedChatInput:
        image_context = ""
        image_inputs = []
        native = bool(image_urls and self.native_vision())
        if image_urls and self.image_limiter.allow(user_id):
            if native:
                image_inputs, image_context = await self._prepare_images(image_urls)
            else:
                image_context = await self._describe_images(image_urls)
        elif image_urls:
            self._deps.logger.info(
                "图片处理被速率限制拦截 user_id={} image_count={}",
                user_id,
                len(image_urls),
            )
            image_context = "本次图片处理被限频拦截，没有可见图片；请稍后重发。"

        llm_text = user_text
        if image_urls:
            image_evidence = image_context or "图片识别未返回可用结果。"
            marker = "图片输入状态" if native else "图片识别结果"
            llm_text = f"{user_text or '用户发送了图片。'}\n\n[{marker}]\n{image_evidence}"
        raw_search_outcome = await self.search_builder.build(
            user_text,
            image_context=image_context,
            recent_history=history,
        )
        if isinstance(raw_search_outcome, SearchOutcome):
            search_outcome = raw_search_outcome
            search_context = search_outcome.context_text()
        else:
            # Keep lightweight injected builders used by integrations and
            # older tests compatible while the production builder stays typed.
            search_context = str(raw_search_outcome or "")
            search_outcome = SearchOutcome(
                required=bool(search_context),
                attempted=bool(search_context),
                success=bool(search_context),
                factual_mode=bool(search_context),
            )
        if search_context:
            llm_text = f"{llm_text}\n\n{search_context}"
        return EnrichedChatInput(
            user_text,
            llm_text,
            image_context,
            search_context,
            search_outcome,
            image_inputs,
        )

    async def _prepare_images(self, image_urls):
        inputs, lines = [], []
        # Sequential downloads keep memory bounded on small deployments.
        for index, url in enumerate(image_urls[:MAX_IMAGES_TO_DESCRIBE], 1):
            try:
                inputs.append(await self.prepare(url))
                lines.append(f"第{index}张图片已附加，请直接读取图片。")
            except Exception as exc:
                self._deps.logger.warning("图片输入准备失败({}): {}", index, type(exc).__name__)
                lines.append(f"第{index}张图片下载或校验失败，未附加；不能猜测其内容。")
        remaining = len(image_urls) - MAX_IMAGES_TO_DESCRIBE
        if remaining > 0:
            lines.append(f"还有{remaining}张图片未附加。")
        return inputs, "\n".join(lines)

    async def _describe_images(self, image_urls: List[str]) -> str:
        async def describe_one(index: int, url: str) -> str:
            try:
                description = await self.describe(url)
                return f"第{index}张图片：{description or '图片识别没有返回可用描述。'}"
            except Exception as exc:
                self._deps.logger.warning(f"图片识别失败({index}): {exc}")
                return f"第{index}张图片识别失败：{exc}"

        urls = image_urls[:MAX_IMAGES_TO_DESCRIBE]
        lines = await self._deps.asyncio.gather(
            *(describe_one(index, url) for index, url in enumerate(urls, start=1))
        )
        remaining = len(image_urls) - len(urls)
        if remaining:
            lines.append(f"还有{remaining}张图片未识别。")
        return "\n".join(lines)
