"""行情刷新互斥锁，避免定时任务与手动刷新并发执行。"""

import logging
import threading

logger = logging.getLogger(__name__)

_exec_lock = threading.Lock()


def is_refresh_locked() -> bool:
    return _exec_lock.locked()


def try_run_refresh(fn, *args, **kwargs) -> bool:
    """尝试执行刷新；若已有任务在跑则返回 False。"""
    if not _exec_lock.acquire(blocking=False):
        logger.info("行情刷新跳过：已有任务执行中")
        return False
    try:
        fn(*args, **kwargs)
        return True
    finally:
        _exec_lock.release()
