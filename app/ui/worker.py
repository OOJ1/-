"""解题工作线程。

网络请求是阻塞式的流式读取，必须放在后台线程，主线程只接收信号刷新界面。
"""

from __future__ import annotations

import time
from dataclasses import replace

from PySide6.QtCore import QThread, Signal

from app.config import EngineConfig
from app.engine.base import EMPTY_ANSWER_HINT, EngineError, SolveRequest
from app.engine.service import build_provider
from app.logger import get

log = get("worker")


class SolveWorker(QThread):
    chunk = Signal(str)
    done = Signal(str, int)  # 完整答案, 耗时毫秒
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, cfg: EngineConfig, req: SolveRequest, parent=None) -> None:
        super().__init__(parent)
        # 深拷贝一份配置，避免运行期间用户改设置导致线程读到半成品
        self.cfg: EngineConfig = replace(cfg)
        self.req = req
        self._cancel = False
        self._parts: list[str] = []

    def cancel(self) -> None:
        self._cancel = True

    @property
    def answer(self) -> str:
        return "".join(self._parts).strip()

    def run(self) -> None:  # noqa: D102
        start = time.time()
        try:
            provider = build_provider(self.cfg)
            for piece in provider.stream(self.req):
                if self._cancel:
                    break
                self._parts.append(piece)
                self.chunk.emit(piece)
        except EngineError as e:
            if self._cancel:
                self.cancelled.emit()
            else:
                self.failed.emit(str(e))
            return
        except Exception as e:  # noqa: BLE001
            log.exception("解题线程异常")
            if self._cancel:
                self.cancelled.emit()
            else:
                self.failed.emit(f"未预期的错误：{e}")
            return

        if self._cancel:
            self.cancelled.emit()
            return
        # 空答案必须报错：否则界面只显示一片空白，用户完全不知道发生了什么
        if not self.answer:
            self.failed.emit(EMPTY_ANSWER_HINT)
            return
        self.done.emit(self.answer, int((time.time() - start) * 1000))


class TestWorker(QThread):
    """设置页的「测试连接」：不阻塞界面。"""

    finished_test = Signal(bool, str)

    def __init__(self, cfg: EngineConfig, parent=None) -> None:
        super().__init__(parent)
        self.cfg: EngineConfig = replace(cfg)

    def run(self) -> None:  # noqa: D102
        try:
            provider = build_provider(self.cfg)
            ok, msg = provider.test()
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"测试失败：{e}"
        self.finished_test.emit(ok, msg)
