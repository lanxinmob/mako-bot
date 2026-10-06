import src.services.persistence.backends.memory as storage_module
from src.services.persistence import StorageService


def test_sent_news_is_persisted_in_memory_backend() -> None:
    service = StorageService()
    service.redis = None
    storage_module.memory_store.sent_news.clear()

    service.record_sent_news(["first", "second", "first", ""])

    assert service.list_sent_news() == {"first", "second"}
