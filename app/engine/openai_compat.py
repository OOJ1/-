"""OpenAI 兼容协议实现（覆盖 Ollama /v1、通义、智谱、DeepSeek、OpenAI 等）。"""

from __future__ import annotations

from typing import Iterator

import httpx

from app.engine.base import BaseProvider, SolveRequest, merge_extra_body, parse_sse_lines

DEFAULT_IMAGE_PROMPT = "请解答这道题，按系统要求给出步骤和最终答案。"


class OpenAICompatProvider(BaseProvider):
    name = "openai"

    def url(self) -> str:
        base = (self.cfg.base_url or "").strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _build_content(self, req: SolveRequest):
        text = (req.question or "").strip()
        if not req.has_image:
            return text or "你好"
        return [
            {"type": "text", "text": text or DEFAULT_IMAGE_PROMPT},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{req.image_mime};base64,{req.image_b64}"},
            },
        ]

    def payload(self, req: SolveRequest, *, stream: bool = True) -> dict:
        messages = []
        prompt = self.cfg.resolved_system_prompt()
        if prompt:
            messages.append({"role": "system", "content": prompt})
        messages.append({"role": "user", "content": self._build_content(req)})
        body = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": float(self.cfg.temperature),
            "stream": bool(stream),
        }
        limit = self.cfg.resolved_max_tokens()
        if limit > 0:
            body["max_tokens"] = int(limit)
        return merge_extra_body(body, self.cfg)

    def iter_text(self, resp: httpx.Response) -> Iterator[str]:
        yield from parse_sse_lines(resp)
