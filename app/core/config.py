from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Health Bridge API"
    ENV: str = "dev"

    MONGO_URI: str
    MONGO_DB: str

    JWT_SECRET: str
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 60
    REFRESH_TOKEN_DAYS: int = 30

    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_WEBHOOK_SECRET: str | None = None

    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None
    DOCTOR_DEFAULT_PASSWORD: str = "Doctor@123"


settings = Settings()
