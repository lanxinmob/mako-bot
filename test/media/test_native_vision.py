import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.config import Settings
from src.core.errors import ImageTooLargeError
from src.services.chat.context import ChatContextBuilder, ImageRateLimiter
from src.services.chat.engine import ChatEngine
from src.services.chat.models import ChatRequest
from src.services.chat.generation.invocation import RecordedInvocation
from src.services.integrations import vision_input
from test.media.image_fixtures import _make_png_bytes


def builder(**kwargs):
    return ChatContextBuilder(search_builder=SimpleNamespace(build=AsyncMock(return_value="")),
        image_limiter=ImageRateLimiter(interval_seconds=0), native_vision=lambda: True, **kwargs)


@pytest.mark.asyncio
async def test_native_images_reach_the_same_generation_call_without_description_or_history_bytes():
    data = vision_input.inline_image(_make_png_bytes(20, 20))
    describe = AsyncMock(side_effect=AssertionError("native images must not call a separate model"))
    context = await builder(prepare=AsyncMock(return_value=data), describe=describe).build(
        user_id=7, user_text="这个表情什么意思？", image_urls=["https://example.com/a.png"], history=[])
    storage = SimpleNamespace(get_profile=lambda _: None)
    request = ChatRequest("private_7", 7, "测试", context.user_text, context.llm_text, [],
                          image_inputs=context.image_inputs)
    engine = ChatEngine(storage=storage, knowledge_search=lambda _: [],
                        runtime_context=SimpleNamespace(build_for_user=lambda _: ""))
    messages = engine._build_messages(request)
    assert messages[-1]["content"][0]["type"] == "text"
    assert "这个表情什么意思" in messages[-1]["content"][0]["text"]
    assert messages[-1]["content"][1] == {"type": "image_url", "image_url": {"url": data}}
    assert "图片识别未返回" not in context.llm_text
    describe.assert_not_awaited()
    assert data not in str(engine._next_history(request, "这是失落的表情。"))
    store = SimpleNamespace(start=Mock(return_value="token"), complete=Mock(return_value="completed"))
    provider = AsyncMock(return_value="这是失落的表情。")
    result = await RecordedInvocation(store, input_rate=1, output_rate=1).call(
        provider, messages, user_id=7, phase="reply", model="deepseek-v4-flash-vision", max_output_chars=100)
    provider.assert_awaited_once_with(messages)
    assert result.cost_status == "recorded"
    assert data not in repr(store.start.call_args.args[0])


@pytest.mark.asyncio
async def test_limit_partial_failure_and_rate_limit_never_forward_unchecked_urls():
    data = vision_input.inline_image(_make_png_bytes(2, 2))
    prepare = AsyncMock(side_effect=[data, OSError("do not leak URL secrets"), data])
    context_builder = builder(prepare=prepare)
    result = await context_builder.build(user_id=7, user_text="看图", image_urls=["a", "b", "c", "d"], history=[])
    assert result.image_inputs == [data, data]
    assert prepare.await_count == 3
    assert "第2张图片下载或校验失败" in result.image_context
    assert "还有1张图片未附加" in result.image_context
    assert "do not leak" not in result.llm_text
    context_builder.image_limiter = SimpleNamespace(allow=lambda _: False)
    limited = await context_builder.build(user_id=7, user_text="看图", image_urls=["a"], history=[])
    assert not limited.image_inputs and "限频" in limited.llm_text
    assert prepare.await_count == 3


@pytest.mark.parametrize("model,key,openai,expected", [
    ("deepseek-v4-flash-vision", "fake", None, True),
    ("deepseek-v4-flash", "fake", "fake", False),
    ("deepseek-v4-flash-vision", None, None, False),
    ("", None, "fake", True),
])
def test_only_selected_provider_with_known_image_input_uses_native_path(model, key, openai, expected):
    settings = SimpleNamespace(deepseek_model=model, deepseek_api_key=key, openai_api_key=openai)
    assert vision_input.native_vision_enabled(settings) is expected


@pytest.mark.asyncio
async def test_inline_preparation_uses_real_format_and_existing_bounded_download(monkeypatch):
    content = _make_png_bytes(20, 20)
    download = AsyncMock(return_value=(content, "image/jpeg"))
    monkeypatch.setattr(vision_input, "download_image_data", download)
    result = await vision_input.prepare_native_image("https://example.com/a")
    assert result.startswith("data:image/png;base64,")
    assert base64.b64decode(result.split(",", 1)[1]) == content
    download.assert_awaited_once()
    download.side_effect = ImageTooLargeError("too large")
    with pytest.raises(ImageTooLargeError):
        await vision_input.prepare_native_image("https://example.com/b")


def test_dimensions_and_invalid_image_bytes_are_rejected(monkeypatch):
    from src.services.integrations import image
    from PIL import UnidentifiedImageError
    monkeypatch.setattr(image, "get_settings", lambda: Settings(_env_file=None, IMAGE_MAX_WIDTH=10))
    with pytest.raises(ImageTooLargeError):
        vision_input.inline_image(_make_png_bytes(20, 20))
    with pytest.raises(UnidentifiedImageError):
        vision_input.inline_image(b"not an image")


@pytest.mark.asyncio
@pytest.mark.parametrize("part", [
    {"type": "image_url", "image_url": {"url": "http://127.0.0.1/secret"}},
    {"type": "image_url", "image_url": "data:image/png;base64,x"},
    {"type": "text", "text": 42}, {"type": "unknown"},
])
async def test_malformed_multimodal_input_is_rejected_before_persistence_or_provider(part):
    store, provider = Mock(), AsyncMock()
    with pytest.raises(ValueError):
        await RecordedInvocation(store, input_rate=1, output_rate=1).call(provider,
            [{"role": "user", "content": [part]}], user_id=7, phase="reply", model="test", max_output_chars=10)
    assert not store.mock_calls
    provider.assert_not_awaited()
