"""Media safety: context."""
from __future__ import annotations
import inspect
import pytest
from src.core.config import get_settings
from src.services.chat.context import ChatContextBuilder
from src.services.chat.context import ImageRateLimiter


class TestImageRateLimiter:
    """ImageRateLimiter is directly testable without importing the plugin."""

    def test_first_call_allowed(self):
        limiter = ImageRateLimiter(interval_seconds=30)
        assert limiter.allow(12345, now=100.0) is True

    def test_rapid_second_call_blocked(self):
        limiter = ImageRateLimiter(interval_seconds=30)
        assert limiter.allow(12345, now=100.0) is True
        assert limiter.allow(12345, now=101.0) is False

    def test_allowed_after_cooldown(self):
        limiter = ImageRateLimiter(interval_seconds=1)
        assert limiter.allow(12345, now=100.0) is True
        assert limiter.allow(12345, now=100.5) is False
        assert limiter.allow(12345, now=101.5) is True

    def test_different_users_independent(self):
        limiter = ImageRateLimiter(interval_seconds=30)
        assert limiter.allow(111, now=100.0) is True
        assert limiter.allow(222, now=100.0) is True
        assert limiter.allow(111, now=101.0) is False

    def test_uses_config_default_rate_limit_seconds(self):
        limiter = ImageRateLimiter()
        assert limiter.interval_seconds == get_settings().image_rate_limit_seconds


class TestGeminiBase64Offload:
    """Verify that describe_image_with_gemini offloads b64encode to a thread."""

    def test_uses_asyncio_to_thread_for_base64(self):
        import src.services.integrations.gemini as gemini

        source = inspect.getsource(gemini.describe_image_with_gemini)
        assert "asyncio.to_thread(base64.b64encode" in source.replace(" ", ""), (
            "Expected asyncio.to_thread(base64.b64encode,...) in describe_image_with_gemini"
        )

    def test_function_is_async(self):
        from src.services.integrations.gemini import describe_image_with_gemini

        assert inspect.iscoroutinefunction(describe_image_with_gemini)


class TestBuildImageContext:
    """Image enrichment is tested through its public service contract."""

    class NoSearch:
        async def build(self, *args, **kwargs):
            return ""

    @pytest.mark.asyncio
    async def test_empty_urls_returns_empty(self):
        builder = ChatContextBuilder(search_builder=self.NoSearch())
        result = await builder.build(user_id=1, user_text="hello", image_urls=[], history=[])
        assert result.image_context == ""
        assert result.llm_text == "hello"

    @pytest.mark.asyncio
    async def test_describes_images_concurrently(self):
        active = 0
        max_active = 0

        async def describe(url: str) -> str:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await __import__("asyncio").sleep(0)
            active -= 1
            return url

        builder = ChatContextBuilder(
            search_builder=self.NoSearch(),
            image_limiter=ImageRateLimiter(interval_seconds=0),
            describe=describe,
        )
        result = await builder.build(
            user_id=1,
            user_text="",
            image_urls=["a", "b", "c"],
            history=[],
        )
        assert max_active == 3
        assert "第1张图片：a" in result.image_context

    @pytest.mark.asyncio
    async def test_caps_images_and_reports_remaining_count(self):
        seen = []

        async def describe(url: str) -> str:
            seen.append(url)
            return url

        builder = ChatContextBuilder(
            search_builder=self.NoSearch(),
            image_limiter=ImageRateLimiter(interval_seconds=0),
            describe=describe,
        )
        result = await builder.build(
            user_id=1,
            user_text="看图",
            image_urls=["1", "2", "3", "4", "5"],
            history=[],
        )
        assert seen == ["1", "2", "3"]
        assert "还有2张图片未识别" in result.image_context

    @pytest.mark.asyncio
    async def test_individual_description_failure_is_isolated(self):
        async def describe(url: str) -> str:
            if url == "bad":
                raise RuntimeError("broken")
            return url

        builder = ChatContextBuilder(
            search_builder=self.NoSearch(),
            image_limiter=ImageRateLimiter(interval_seconds=0),
            describe=describe,
        )
        result = await builder.build(
            user_id=1,
            user_text="看图",
            image_urls=["ok", "bad"],
            history=[],
        )
        assert "第1张图片：ok" in result.image_context
        assert "第2张图片识别失败：broken" in result.image_context
