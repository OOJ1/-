"""日志：滚动文件 + 控制台。日志目录位于数据根目录下，随数据一起清理。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import config as cfgmod

_LOGGER_NAME = "jige"
_configured = False


def setup(level: int = logging.INFO, console: bool = True) -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logs = cfgmod.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = RotatingFileHandler(logs / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if console and sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(level)
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    _configured = True
    return logger


def get(name: str = "") -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME if not name else f"{_LOGGER_NAME}.{name}")
    if not _configured:
        setup()
    return logger


def install_excepthook() -> None:
    """把未捕获异常写进日志，便于排查（同时保留控制台输出）。"""
    log = get("crash")

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = hook


def cleanup_logs(max_age_days: int = 7) -> int:
    """清理过期滚动日志，返回删除文件数。"""
    removed = 0
    logs = cfgmod.logs_dir()
    if not logs.exists():
        return 0
    import time

    cutoff = time.time() - max_age_days * 86400
    for p in logs.glob("app.log.*"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed
