from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    backend_base_url: str = "http://localhost:8080/api"
    redis_url: str = "redis://localhost:6379/0"
    ai_service_shared_secret: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
