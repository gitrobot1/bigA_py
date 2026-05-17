import logging
from functools import lru_cache

import redis
from redis import Redis

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache()
def get_redis() -> Redis:
    cfg = get_settings().redis
    client = redis.Redis(
        host=cfg.host,
        port=cfg.port,
        db=cfg.db,
        password=cfg.password or None,
        decode_responses=True,
    )
    client.ping()
    logger.info("Redis 已连接 %s:%s/%s", cfg.host, cfg.port, cfg.db)
    return client


def check_redis() -> bool:
    try:
        get_redis().ping()
        return True
    except Exception as e:
        logger.warning("Redis 不可用: %s", e)
        return False
