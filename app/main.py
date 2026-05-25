import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from sqlalchemy import text

from app.config import get_settings
from app.core.database import SessionLocal, init_db
from app.core.openapi import OPENAPI_DESCRIPTION, OPENAPI_TAGS
from app.core.redis_client import check_redis
from app.routers import api_router
from app.services.quote_cache import quote_cache
from app.services.quote_provider import warmup_fund_name_cache
from app.services.refresh_job import get_refresh_status
from app.services.scheduler import start_scheduler, stop_scheduler

settings = get_settings()


def _setup_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


_setup_logging()
logger = logging.getLogger(__name__)


def _check_database() -> bool:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("数据库不可用: %s", e)
        return False
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        quote_cache.load_all(db)
    finally:
        db.close()
    start_scheduler()
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, warmup_fund_name_cache)
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.SWAGGER_TITLE,
    version=settings.APP_VERSION,
    description=OPENAPI_DESCRIPTION,
    docs_url="/api/doc",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=OPENAPI_TAGS,
    )
    schema["components"]["securitySchemes"] = {
        "OAuth2PasswordBearer": {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": "/api/v1/users/login",
                    "scopes": {},
                }
            },
            "description": "先调用登录接口获取 access_token，再在此填入 Bearer <token>",
        }
    }
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.get("/", tags=["系统"], summary="服务首页")
def root():
    """返回 API 名称、文档入口与当前轮询间隔。"""
    return {
        "message": "BigA 行情分析 API",
        "docs": "/api/doc",
        "redoc": "/api/redoc",
        "poll_interval_seconds": settings.POLL_INTERVAL_SECONDS,
        "macro_refresh_every_n_polls": settings.MACRO_REFRESH_EVERY_N_POLLS,
    }


@app.get("/health", tags=["系统"], summary="健康检查")
def health_check():
    """检查服务、数据库、Redis 及最近一次行情刷新状态。"""
    db_ok = _check_database()
    redis_ok = check_redis()
    cache = quote_cache.status()
    refresh = get_refresh_status()
    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "config_file": str(settings.config_file),
        "database": settings.database.name,
        "database_ok": db_ok,
        "redis": redis_ok,
        "last_refresh": cache.get("last_refresh"),
        "last_error": cache.get("last_error"),
        "quote_count": cache.get("quote_count"),
        "refresh_job": refresh.get("status"),
    }
