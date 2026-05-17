from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.config import get_settings
from app.core.database import SessionLocal, init_db
from app.core.openapi import OPENAPI_DESCRIPTION, OPENAPI_TAGS
from app.core.redis_client import check_redis
from app.routers import api_router
from app.services.quote_cache import quote_cache
from app.services.scheduler import start_scheduler, stop_scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        quote_cache.load_all(db)
    finally:
        db.close()
    start_scheduler()
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
    }


@app.get("/health", tags=["系统"], summary="健康检查")
def health_check():
    """检查服务、配置文件路径及 Redis 连通性。"""
    return {
        "status": "ok",
        "config_file": str(settings.config_file),
        "database": settings.database.name,
        "redis": check_redis(),
    }
