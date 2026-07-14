from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    nebius_tokenfactory_api_key: str = ""
    nebius_base_url: str = "https://api.studio.nebius.ai/v1"
    nebius_tokenfactory_model_dev: str

    nebius_s3_endpoint_url: str = ""
    nebius_s3_bucket: str = "silicon-sample"
    nebius_s3_region: str = "eu-north1"
    nebius_s3_access_key_id: str = ""
    nebius_s3_secret_access_key: str = ""

    duckdb_path: str = "data/panel.duckdb"


@lru_cache
def get_settings() -> Settings:
    return Settings()
