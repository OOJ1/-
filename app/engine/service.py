"""引擎工厂：按配置组装出可用的 Provider 实例。"""

from __future__ import annotations

import threading
from dataclasses import replace

from app.config import DEFAULT_KEEP_ALIVE, EngineConfig
from app.engine.base import (
    BaseProvider,
    EngineError,
    SolveRequest,
    SolveResult,
    _is_local,
    _origin_of,
    make_client,
    translate_network_error,
)
from app.engine.ollama_native import OllamaNativeProvider
from app.engine.openai_compat import OpenAICompatProvider
from app.logger import get

log = get("engine")

WIRE_OPENAI = "openai"
WIRE_OLLAMA = "ollama_native"

WIRE_CHOICES = [
    (WIRE_OPENAI, "OpenAI 兼容（云端服务通用）"),
    (WIRE_OLLAMA, "Ollama 原生协议（本机 Ollama 推荐）"),
]

PRELOAD_TIMEOUT = 300.0  # 冷启动要把权重读进显存，给它足够时间


def build_provider(cfg: EngineConfig) -> BaseProvider:
    if cfg.wire_api == WIRE_OLLAMA:
        provider: BaseProvider = OllamaNativeProvider(cfg)
    else:
        provider = OpenAICompatProvider(cfg)
    # 展示名跟随服务商，便于历史记录里区分来源
    provider.name = cfg.provider or provider.name
    return provider


def is_local_service(cfg: EngineConfig) -> bool:
    """是否指向本机服务（本机服务才值得预热，云端预热还要花钱）。"""
    return _is_local(cfg.base_url) or cfg.wire_api == WIRE_OLLAMA


def preload_local_model(cfg: EngineConfig) -> str:
    """把本机模型提前读进显存。成功返回空串，否则返回原因（只用于日志）。

    为什么单独做这一步：Ollama 默认 5 分钟就把模型卸载，下次提问要重新加载权重，
    本机实测 9B 模型冷启动约 74 秒、热态只要 5-12 秒。
    这里用 `/api/generate` 只带 `keep_alive`、不带 prompt —— Ollama 会加载模型并立即返回，
    不产生任何 token，是最省的一次「点醒」。

    失败不抛异常：预热只是优化，绝不能让应用启动失败。
    """
    if not is_local_service(cfg):
        return "非本机服务，跳过预热"
    model = (cfg.model or "").strip()
    if not model:
        return "尚未配置模型名，跳过预热"
    root = _origin_of(cfg.base_url) or (cfg.base_url or "").rstrip("/")
    if not root:
        return "base_url 为空，跳过预热"
    payload = {"model": model, "keep_alive": cfg.resolved_keep_alive() or DEFAULT_KEEP_ALIVE}
    try:
        with make_client(cfg) as client:
            resp = client.post(f"{root}/api/generate", json=payload, timeout=PRELOAD_TIMEOUT)
            if resp.status_code >= 400:
                # 模型没装是最常见的一种。光记一句「HTTP 404」对排查毫无帮助，
                # 直接把「该去设置里换一个」写进日志（首次启动时预设模型常常没 pull 过）。
                if resp.status_code == 404:
                    return (
                        f"预热未进行：模型「{model}」在本机服务上不存在。"
                        "请在「设置 → 引擎」点「检测本机模型」换一个，或执行 "
                        f"`ollama pull {model}` 把它拉下来。"
                    )
                return f"预热未进行：HTTP {resp.status_code}"
    except EngineError:
        raise  # make_client 的配置类错误要暴露出来
    except Exception as e:  # noqa: BLE001
        return f"预热未进行：{translate_network_error(e, cfg.base_url)}"
    return ""


def warm_up_async(cfg: EngineConfig) -> threading.Thread:
    """后台线程预热，不阻塞界面。返回线程对象，便于测试时 join。"""
    snapshot = replace(cfg)  # 拷贝一份，避免线程读到用户改到一半的配置

    def _run() -> None:
        reason = preload_local_model(snapshot)
        if reason:
            # reason 本身就是一句完整的中文说明，直接原样记下来即可
            log.info("%s", reason)
        else:
            log.info("模型预热完成：%s（keep_alive=%s）", snapshot.model, snapshot.resolved_keep_alive())

    t = threading.Thread(target=_run, name="jige-prewarm", daemon=True)
    t.start()
    return t


__all__ = [
    "BaseProvider",
    "EngineError",
    "SolveRequest",
    "SolveResult",
    "build_provider",
    "is_local_service",
    "make_client",
    "preload_local_model",
    "warm_up_async",
]
