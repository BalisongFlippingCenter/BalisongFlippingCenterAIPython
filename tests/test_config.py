from app.config import Settings


def test_defaults_match_expected_values(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("BACKEND_BASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("AI_SERVICE_SHARED_SECRET", raising=False)

    settings = Settings(_env_file=None)

    assert settings.aws_region == "us-east-1"
    assert settings.bedrock_model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert settings.backend_base_url == "http://localhost:8080/api"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.ai_service_shared_secret == ""


def test_reads_overrides_from_environment(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("BACKEND_BASE_URL", "https://api.example.com")

    settings = Settings(_env_file=None)

    assert settings.aws_region == "eu-west-1"
    assert settings.backend_base_url == "https://api.example.com"
