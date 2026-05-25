import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

import yaml
from dotenv import load_dotenv

load_dotenv()
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = BASE_DIR / "config" / "settings.yaml"


class AppConfig(BaseModel):
    name: str = "BigA 行情分析"
    version: str = "2.0.0"
    debug: bool = True
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    poll_interval_seconds: int = 300
    macro_refresh_every_n_polls: int = 3
    log_level: str = "INFO"
    search_cache_seconds: int = 120
    swagger_title: str = "BigA Market API"
    swagger_description: str = ""


class DatabaseConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 3306
    name: str = "bigA_db"
    user: str = "admin"
    password: str = "123456"
    charset: str = "utf8mb4"

    @property
    def url(self) -> str:
        user = quote_plus(self.user)
        password = quote_plus(self.password)
        return (
            f"mysql+pymysql://{user}:{password}@{self.host}:{self.port}"
            f"/{self.name}?charset={self.charset}"
        )


class RedisConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 6379
    db: int = 0
    password: str = ""

    @property
    def url(self) -> str:
        if self.password:
            auth = f":{quote_plus(self.password)}@"
        else:
            auth = ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class SettingsRoot(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)


class Settings:
    """对外暴露的配置门面，兼容原有 settings.XXX 访问方式。"""

    def __init__(self, root: SettingsRoot, config_file: Path):
        self._root = root
        self.config_file = config_file

    @property
    def app(self) -> AppConfig:
        return self._root.app

    @property
    def database(self) -> DatabaseConfig:
        return self._root.database

    @property
    def redis(self) -> RedisConfig:
        return self._root.redis

    @property
    def APP_NAME(self) -> str:
        return self.app.name

    @property
    def APP_VERSION(self) -> str:
        return self.app.version

    @property
    def DEBUG(self) -> bool:
        return self.app.debug

    @property
    def SECRET_KEY(self) -> str:
        return self.app.secret_key

    @property
    def ALGORITHM(self) -> str:
        return self.app.algorithm

    @property
    def ACCESS_TOKEN_EXPIRE_MINUTES(self) -> int:
        return self.app.access_token_expire_minutes

    @property
    def POLL_INTERVAL_SECONDS(self) -> int:
        return self.app.poll_interval_seconds

    @property
    def MACRO_REFRESH_EVERY_N_POLLS(self) -> int:
        return self.app.macro_refresh_every_n_polls

    @property
    def LOG_LEVEL(self) -> str:
        return self.app.log_level

    @property
    def SEARCH_CACHE_SECONDS(self) -> int:
        return self.app.search_cache_seconds

    @property
    def SWAGGER_TITLE(self) -> str:
        return self.app.swagger_title

    @property
    def SWAGGER_DESCRIPTION(self) -> str:
        return self.app.swagger_description

    @property
    def DATABASE_URL(self) -> str:
        return self.database.url

    @property
    def REDIS_URL(self) -> str:
        return self.redis.url


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or Path(os.getenv("CONFIG_FILE", DEFAULT_CONFIG_FILE))
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    root = SettingsRoot.model_validate(data)
    return Settings(root, path)


@lru_cache()
def get_settings() -> Settings:
    return load_settings()
