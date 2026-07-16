from src.core.config import Settings


def test_deepseek_model_defaults_to_v4_flash() -> None:
    settings = Settings(_env_file=None)
    assert settings.deepseek_model == "deepseek-v4-flash"


def test_deepseek_model_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    settings = Settings(_env_file=None)
    assert settings.deepseek_model == "deepseek-v4-pro"
