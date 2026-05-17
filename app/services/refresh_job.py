import logging
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_refresh_thread: threading.Thread | None = None

_state: dict[str, Any] = {
    "status": "idle",  # idle | running | done | failed
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def get_refresh_status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def is_refresh_running() -> bool:
    with _lock:
        return _state["status"] == "running"


def _set_state(**kwargs) -> None:
    with _lock:
        _state.update(kwargs)


def _run_refresh(fast: bool) -> None:
    from app.services.scheduler import refresh_market_data

    _set_state(status="running", started_at=datetime.utcnow().isoformat() + "Z", finished_at=None, error=None)
    try:
        refresh_market_data(fast=fast)
        _set_state(status="done", finished_at=datetime.utcnow().isoformat() + "Z", error=None)
        logger.info("后台行情刷新完成")
    except Exception as e:
        logger.exception("后台行情刷新失败")
        _set_state(status="failed", finished_at=datetime.utcnow().isoformat() + "Z", error=str(e))


def trigger_refresh_background(fast: bool = True) -> tuple[bool, str]:
    """启动后台刷新。若已在刷新中则返回 False。"""
    global _refresh_thread
    with _lock:
        if _state["status"] == "running":
            return False, "已有刷新任务进行中，请稍后查询 /market/refresh/status"
        _refresh_thread = threading.Thread(target=_run_refresh, args=(fast,), daemon=True)
        _refresh_thread.start()
    return True, "刷新任务已提交，请轮询 /api/v1/market/refresh/status 获取结果"
