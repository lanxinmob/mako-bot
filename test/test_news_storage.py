from src.services import storage as storage_module
from src.services.storage import StorageService


def test_sent_news_is_persisted_in_memory_backend() -> None:
    service = StorageService()
    service.redis = None
    storage_module._memory.sent_news.clear()

    service.record_sent_news(["first", "second", "first", ""])

    assert service.list_sent_news() == {"first", "second"}
