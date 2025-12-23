from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    APP_NAME: str = "CustomRMM Alpha"
    BASE_URL: str = "http://localhost:8000"
    SECRET_KEY: str = "change-me"
    SESSION_COOKIE_NAME: str = "customrmm_session"
    DB_URL: str = "sqlite:///./data/customrmm.db"

    PASSWORD_MIN_LEN: int = 10
    LOGIN_RATE_LIMIT_PER_MIN: int = 20

    DEVICE_OFFLINE_MINUTES: int = 10

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASS: str | None = None
    SMTP_FROM: str | None = None

    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_FROM: str | None = None
    ALERT_SMS_TO: str | None = None

settings = Settings()
