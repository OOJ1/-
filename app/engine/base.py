"""引擎抽象层。

对外只有三个概念：
- SolveRequest：一次解题请求（题干 + 可选的图片 base64）
- BaseProvider：服务商实现，只需覆写 url / payload / iter_text 三个钩子
- EngineError：带中文提示的异常，UI 直接展示给用户

新增服务商：继承 BaseProvider 覆写三个钩子即可；纯文本/图片差异由 payload 统一处理。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlparse

import httpx

from app.config import EngineConfig

CONNECT_TIMEOUT = 15
READ_TIMEOUT_PAD = 30

EMPTY_ANSWER_HINT = (
    "模型没有返回任何内容。常见原因：\n"
    "1. 该模型带「思考模式」，输出预算被内部推理耗尽 "
    '—— 在「设置 → 引擎 → 额外请求参数」里填 {"think": false}；\n'
    "2. 「最大输出」设得太小 —— 调大到 2048 以上；\n"
    "3. 本机 Ollama 的 OpenAI 兼容端点对视觉/思考模型支持不佳 "
    "—— 把「接口协议」换成「Ollama 原生协议」。"
)


class EngineError(Exception):
    """面向用户的错误，message 已是可直接展示的中文说明。"""


@dataclass
class SolveRequest:
    question: str = ""
    image_b64: str = ""  # 不含 data: 前缀
    image_mime: str = "image/jpeg"

    @property
    def has_image(self) -> bool:
        return bool(self.image_b64)


@dataclass
class SolveResult:
    answer: str = ""
    provider: str = ""
    model: str = ""
    elapsed_ms: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _is_local(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def make_client(cfg: EngineConfig) -> httpx.Client:
    """本地地址强制忽略系统代理。

    否则从带 http_proxy 的终端/IDE 启动时，连本机 Ollama 的请求会被塞进代理导致失败
    （这是很常见的"小请求正常、流式请求中断"类故障根因）。
    """
    timeout = httpx.Timeout(cfg.timeout, connect=CONNECT_TIMEOUT)
    local = _is_local(cfg.base_url)
    try:
        return httpx.Client(timeout=timeout, trust_env=not local, follow_redirects=True)
    except Exception as e:  # noqa: BLE001
        raise EngineError(f"初始化网络客户端失败：{e}") from e


def parse_extra_body(raw: str) -> dict:
    """解析「额外请求参数」，必须是 JSON 对象。"""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise EngineError(f"「额外请求参数」不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise EngineError('「额外请求参数」必须是 JSON 对象，例如 {"think": false}')
    return data


def merge_extra_body(body: dict, cfg: EngineConfig) -> dict:
    """把「额外请求参数」合并进请求体。

    用于适配各家私有开关（Ollama 的 think、通义的 enable_thinking、智谱的 thinking 等），
    这样新增服务商不必改代码。额外参数会覆盖同名内置字段。
    """
    body.update(parse_extra_body(cfg.extra_body))
    return body


def friendly_http_error(status: int, body: str, base_url: str) -> str:
    body = (body or "").strip()
    if len(body) > 400:
        body = body[:400] + "…"
    tips = {
        401: "API Key 无效或未填写，请在「设置」里检查。",
        403: "无权访问该模型，请确认 Key 的权限或模型名是否正确。",
        404: "接口路径或模型名不存在，请检查 base_url（一般需要以 /v1 结尾）与模型名。",
        429: "请求过于频繁或额度不足，请稍后重试。",
    }
    tip = tips.get(status, "")
    msg = f"服务返回 HTTP {status}。{tip}"
    if _looks_like_missing_model(status, body):
        msg += (
            "\n看起来是**模型名不对**（该模型在服务端不存在）。"
            "在「设置 → 引擎」点「检测本机模型」可以看服务端实际有哪些模型，"
            "或先执行 `ollama pull <模型名>` 把它拉下来。"
        )
    if body:
        msg += f"\n服务端原始信息：{body}"
    return msg


def _looks_like_missing_model(status: int, body: str) -> bool:
    if status not in (400, 404):
        return False
    low = (body or "").lower()
    return any(k in low for k in ("not found", "no such", "does not exist", "not exist", "unknown model", "未找到"))


def _origin_of(url: str) -> str:
    """取 scheme://host:port，丢掉路径。"""
    try:
        p = urlparse(url)
    except ValueError:
        return ""
    if not p.scheme or not p.hostname:
        return ""
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme}://{p.hostname}{port}"


def _probe_headers(cfg: EngineConfig) -> dict[str, str]:
    """探测模型列表用的请求头：有 Key 就带上（云端服务常要求鉴权）。"""
    h = {"Content-Type": "application/json"}
    if (cfg.api_key or "").strip():
        h["Authorization"] = f"Bearer {cfg.api_key.strip()}"
    return h


def detect_models(cfg: EngineConfig) -> list[str]:
    """探测服务端可用的模型名列表。

    本机 Ollama 优先走 /api/tags（信息最全），失败或非 Ollama 时回落到
    OpenAI 兼容的 /v1/models（Ollama 也支持这个路径）。
    返回值已去重排序；连不上或没权限时抛 EngineError（带中文说明）。
    """
    base = (cfg.base_url or "").strip()
    if not base:
        raise EngineError("尚未配置 base_url，请在「设置」里先选择服务商。")

    root = _origin_of(base) or base.rstrip("/")
    is_ollama = cfg.wire_api == "ollama_native" or _is_local(base)
    endpoints: list[str] = []
    if is_ollama:
        endpoints.append(f"{root}/api/tags")
    endpoints.append(f"{base.rstrip('/')}/models")
    if not is_ollama:
        endpoints.append(f"{root}/api/tags")

    last_err = ""
    for url in endpoints:
        try:
            with make_client(cfg) as client:
                resp = client.get(url, headers=_probe_headers(cfg))
                if resp.status_code >= 400:
                    last_err = f"HTTP {resp.status_code}"
                    continue
                data = resp.json()
        except EngineError as e:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = translate_network_error(e, url)
            continue

        names: list[str] = []
        if isinstance(data, dict):
            models = data.get("models")  # Ollama /api/tags
            if isinstance(models, list):
                for m in models:
                    if isinstance(m, dict) and isinstance(m.get("name"), str):
                        names.append(m["name"])
            rows = data.get("data")  # OpenAI /v1/models
            if isinstance(rows, list):
                for m in rows:
                    if isinstance(m, dict):
                        for key in ("id", "name"):
                            if isinstance(m.get(key), str):
                                names.append(m[key])
                                break
        if names:
            return sorted(set(names))
        last_err = f"{url} 返回内容里没有模型列表"

    raise EngineError(f"探测模型列表失败：{last_err}\n请确认服务已启动、base_url 与 API Key 是否正确。")


def _model_matches(model: str, installed: list[str]) -> bool:
    """判断配置的模型名是否在服务端已安装列表中。

    规则从宽到严：忽略大小写精确匹配；配置没写 tag 时，接受服务端的 `名字:latest`。
    **不**把「装了 qwen3.5:9b、配置写 qwen3.5」当成命中——Ollama 会去找
    `qwen3.5:latest`，那并不是已装的 `:9b`，实际请求仍会失败。
    """
    m = (model or "").strip().lower()
    if not m:
        return False
    names = {(n or "").strip().lower() for n in installed}
    if m in names:
        return True
    if ":" not in m and f"{m}:latest" in names:
        return True
    return False


# 「本机服务上没有这个模型」这类错误的稳定标识。
# UI 靠它判断该不该直接弹出「检测本机模型」按钮，避免把「文案有没有改」写成隐式耦合。
MISSING_MODEL_MARK = "本机服务上没有找到模型"


def is_missing_model_error(text: str) -> bool:
    return MISSING_MODEL_MARK in (text or "")


def missing_model_hint(cfg: EngineConfig, installed: list[str]) -> str:
    """本机服务上找不到配置的模型时，给出可执行的修复建议。"""
    model = (cfg.model or "").strip()
    listed = "、".join(installed) if installed else "（列表为空）"
    return (
        f"{MISSING_MODEL_MARK}「{model}」。\n"
        f"当前已安装的模型：{listed}\n"
        f"请二选一：① 在「设置 → 引擎」点「检测本机模型」换成上面已有的；"
        f"② 先执行 `ollama pull {model}` 把它拉下来，再点「测试连接」。"
    )


def translate_network_error(exc: Exception, base_url: str) -> str:
    if isinstance(exc, httpx.ConnectError):
        if _is_local(base_url):
            return (
                f"无法连接本机服务 {base_url}。\n"
                "本机 Ollama 需要先启动（终端执行 ollama serve，或打开 Ollama 客户端）。"
            )
        return f"无法连接 {base_url}，请检查网络或 base_url 是否写对。"
    if isinstance(exc, httpx.ProxyError):
        return f"代理拦截了请求（{base_url}）。请在「设置」中更换服务商或关闭系统代理后重试。"
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return "请求超时。题目或图片较大时请调大「超时时间」，或换用更快的模型。"
    if isinstance(exc, httpx.ConnectTimeout):
        return f"连接 {base_url} 超时，请检查网络。"
    if isinstance(exc, httpx.HTTPError):
        return f"网络请求失败：{exc}"
    return f"未预期的错误：{exc}"


class BaseProvider:
    """服务商基类。子类只需覆写 url / payload / iter_text。"""

    name = "base"

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg

    # -------------------------------------------------------- 钩子

    def url(self) -> str:
        raise NotImplementedError

    def payload(self, req: SolveRequest, *, stream: bool) -> dict:
        raise NotImplementedError

    def iter_text(self, resp: httpx.Response) -> Iterator[str]:
        """从流式响应中逐段取出正文增量。"""
        raise NotImplementedError

    # -------------------------------------------------------- 通用流程

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            h["Authorization"] = f"Bearer {self.cfg.api_key}"
        return h

    def validate(self) -> None:
        if not (self.cfg.base_url or "").strip():
            raise EngineError("尚未配置 base_url，请在「设置」里选择服务商或手动填写。")
        if not (self.cfg.model or "").strip():
            raise EngineError("尚未配置模型名，请在「设置」里填写。")
        if self.cfg.need_key and not (self.cfg.api_key or "").strip():
            raise EngineError("当前服务商需要 API Key，请在「设置」中填写，或改用本机 Ollama。")
        parse_extra_body(self.cfg.extra_body)  # 提前校验，避免发请求才报错

    def stream(self, req: SolveRequest) -> Iterator[str]:
        self.validate()
        payload = self.payload(req, stream=True)
        url = self.url()
        try:
            with make_client(self.cfg) as client:
                with client.stream("POST", url, json=payload, headers=self.headers()) as resp:
                    if resp.status_code >= 400:
                        raise EngineError(
                            friendly_http_error(resp.status_code, resp.read().decode("utf-8", "replace"), url)
                        )
                    for chunk in self.iter_text(resp):
                        if chunk:
                            yield chunk
        except EngineError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EngineError(translate_network_error(e, url)) from e

    def solve(self, req: SolveRequest, on_chunk=None) -> SolveResult:
        start = time.time()
        parts: list[str] = []
        try:
            for chunk in self.stream(req):
                parts.append(chunk)
                if on_chunk:
                    on_chunk(chunk)
        except EngineError as e:
            return SolveResult(
                answer="".join(parts),
                provider=self.name,
                model=self.cfg.model,
                elapsed_ms=int((time.time() - start) * 1000),
                error=str(e),
            )
        return SolveResult(
            answer="".join(parts).strip(),
            provider=self.name,
            model=self.cfg.model,
            elapsed_ms=int((time.time() - start) * 1000),
        )

    def _preflight_model(self) -> str:
        """本机服务上模型名不存在时提前拦下，返回错误文案；一切正常返回空串。

        只对本机服务做这件事：云端服务探测模型列表常需要额外权限，且多发一次请求不划算。
        探测本身失败（服务没启动、超时等）不在这里报错——交给后面的真实请求给出更准确的提示。
        """
        if not (_is_local(self.cfg.base_url) or self.cfg.wire_api == "ollama_native"):
            return ""
        model = (self.cfg.model or "").strip()
        if not model:
            return ""
        try:
            installed = detect_models(self.cfg)
        except EngineError:
            return ""
        if not installed:
            return ""
        if _model_matches(model, installed):
            return ""
        return missing_model_hint(self.cfg, installed)

    def test(self) -> tuple[bool, str]:
        """连通性自检：先核对模型是否存在，再发一个极小的文本请求。"""
        pre = self._preflight_model()
        if pre:
            return False, pre
        req = SolveRequest(question="请只回复两个字：可用")
        start = time.time()
        try:
            res = self.solve(req)
        except Exception as e:  # noqa: BLE001
            return False, f"失败：{e}"
        ms = int((time.time() - start) * 1000)
        if res.ok and (res.answer or "").strip():
            preview = (res.answer or "").replace("\n", " ")[:60]
            return True, f"连接成功（{ms} ms）— 模型回复：{preview}"
        if res.ok:
            return False, f"能连上，但模型没有返回任何内容（耗时 {ms} ms）。\n{EMPTY_ANSWER_HINT}"
        return False, f"{res.error}\n（耗时 {ms} ms）"


def _extract_delta(obj: dict) -> str:
    """兼容 OpenAI 流式响应结构，取出正文增量。"""
    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # 少数服务商返回分片数组
            return "".join(
                p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)
            )
    # 非流式兜底
    msg = choice.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        return msg["content"]
    if isinstance(choice.get("text"), str):
        return choice["text"]
    return ""


def parse_sse_lines(resp: httpx.Response) -> Iterator[str]:
    """解析 OpenAI 风格 SSE：data: {...} / data: [DONE]。"""
    for raw in resp.iter_lines():
        if not raw:
            continue
        line = raw.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            if line == "[DONE]":
                return
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _extract_delta(obj)
            if text:
                yield text
        elif not line.startswith(":"):
            # 个别网关直接吐纯文本增量
            yield line
