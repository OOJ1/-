"""引擎预设：不同服务商的 base_url / 默认模型 / 能力标记。

新增服务商只需在这里加一条，UI 与引擎层自动识别，无需改动其他代码。
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    "ollama": {
        "label": "本机 Ollama（离线免费）",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5vl:7b",
        # 实测 Ollama 的 OpenAI 兼容端点在 thinking 模型上会返回空内容，
        # 原生协议才稳定，故默认走原生协议
        "wire_api": "ollama_native",
        "extra_body": '{"think": false}',
        "need_key": False,
        "vision": True,
        "hint": (
            "需要本机已启动 Ollama 并拉取视觉模型，例如：ollama pull qwen2.5vl:7b。\n"
            "本机默认使用 Ollama 原生协议，并已关闭「思考模式」（{\"think\": false}）："
            "带 thinking 的模型若不关掉，输出预算会被内部推理耗尽，表现为答案空白或被截断。"
        ),
    },
    "dashscope": {
        "label": "阿里通义千问（百炼）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max-latest",
        "wire_api": "openai",
        "extra_body": "",
        "need_key": True,
        "vision": True,
        "hint": "支持图片识别，适合截屏解题。API Key 在阿里云百炼控制台获取。",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v-flash",
        "wire_api": "openai",
        "extra_body": "",
        "need_key": True,
        "vision": True,
        "hint": "glm-4v-flash 免费且支持图片，性价比高。",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "wire_api": "openai",
        "extra_body": "",
        "need_key": True,
        "vision": False,
        "hint": "DeepSeek 目前只有文本模型，截屏解题不可用，仅适合文字输入解题。",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "wire_api": "openai",
        "extra_body": "",
        "need_key": True,
        "vision": True,
        "hint": "需要可访问外网。",
    },
    "custom": {
        "label": "自定义（任意 OpenAI 兼容接口）",
        "base_url": "",
        "model": "",
        "wire_api": "openai",
        "extra_body": "",
        "need_key": True,
        "vision": True,
        "hint": "填写兼容 /chat/completions 的 base_url（需含 /v1），以及模型名。",
    },
}

DEFAULT_PRESET = "ollama"


def get_preset(name: str) -> dict:
    return PRESETS.get(name, PRESETS[DEFAULT_PRESET])


def preset_labels() -> list[tuple[str, str]]:
    """返回 [(key, label), ...]，供下拉框使用。"""
    return [(k, v["label"]) for k, v in PRESETS.items()]
