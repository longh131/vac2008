from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./vac2008.db"
    secret_key: str = "replace-me"
    debug: bool = True
    domain: str = "vac2008.com"
    admin_password: str = "replace-me"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "postmaster@vac2008.com"
    lemonsqueezy_api_key: str = ""
    lemonsqueezy_store_id: str = ""
    lemonsqueezy_variant_id: str = ""
    lemonsqueezy_webhook_secret: str = ""
    lemonsqueezy_checkout_url: str = ""
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_plan_id: str = ""
    paypal_mode: str = "live"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def configured(self, value: str) -> bool:
        text = (value or "").strip()
        return bool(text) and text != "replace-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
