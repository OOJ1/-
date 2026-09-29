"""Ollama 原生协议实现（NDJSON 流）。

相比 OpenAI 兼容层，原生协议对图片字段（images: [b64]）和 num_predict 等参数支持更直接，
作为本机离线场景的备选 wire_api。
"""

from __future__ import annotations

import json
from typing import Iterator

import httpx

from app.engine.base import BaseProvider, SolveRequest, merge_extra_body
from app.engine.openai_compat import DEFAULT_IMAGE_PROMPT


class OllamaNativeProvider(BaseProvider):
    name = "ollama"

    def url(self) -> str:
        base = (self.cfg.base_url or "").strip().rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        if base.endswith("/api/chat"):
            return base
        return f"{base}/api/chat"

    def payload(self, req: SolveRequest, *, stream: bool = True) -> dict:
        user_msg: dict = {
            "role": "user",
            "content": (req.question or "").strip() or DEFAULT_IMAGE_PROMPT,
        }
        if req.has_image:
            user_msg["images"] = [req.image_b64]
        messages = []
        prompt = self.cfg.resolved_system_prompt()
        if prompt:
            messages.append({"role": "system", "content": prompt})
        messages.append(user_msg)
        options: dict = {"temperature": float(self.cfg.temperature)}
        limit = self.cfg.resolved_max_tokens()
        if limit > 0:
            options["num_predict"] = int(limit)
        body: dict = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": bool(stream),
            "options": options,
        }
        # 模型驻留时长（原生协议独有）。不设的话 Ollama 5 分钟就把模型卸掉，
        # 下一次提问又要从磁盘重新加载，实测冷启动 70-90s vs 热态 5-15s。
        keep_alive = self.cfg.resolved_keep_alive()
        if keep_alive:
            body["keep_alive"] = keep_alive
        return merge_extra_body(body, self.cfg)

    def iter_text(self, resp: httpx.Response) -> Iterator[str]:
        for raw in resp.iter_lines():
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj.get("error"), str):
                raise RuntimeError(obj["error"])
            msg = obj.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content:
                    yield content
            if obj.get("done"):
                return
