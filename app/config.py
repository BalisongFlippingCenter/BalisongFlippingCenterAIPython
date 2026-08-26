from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    backend_base_url: str = "http://localhost:8080"

    class Config:
        env_file = ".env"


settings = Settings()
