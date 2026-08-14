"""应用级日志：写入 assistant.log，供排障与运行观察。"""
import logging
import sys
import threading
from pathlib import Path

_LOGGER_NAME = "assistant"
_configured: set = set()


def get_logger(log_dir: Path) -> logging.Logger:
    """返回应用根 logger，首次调用时挂上文件 handler（幂等）。"""
    logger = logging.getLogger(_LOGGER_NAME)
    if log_dir in _configured:
        return logger
    _configured.add(log_dir)
    logger.setLevel(logging.INFO)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(
            log_dir / "assistant.log", encoding="utf-8")
    except OSError:
        return logger
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return logger


def install_excepthook(logger: logging.Logger) -> None:
    """把未捕获异常写进日志（exe 无控制台，闪退必须留现场）。"""

    def _hook(exc_type, exc, tb):
        logger.error("未捕获异常（主线程）",
                     exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def _thread_hook(args):
        logger.error("未捕获异常（线程 %s）", args.thread.name,
                     exc_info=(args.exc_type, args.exc_value,
                               args.exc_traceback))

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
