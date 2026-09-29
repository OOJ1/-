"""配置读写 + 数据目录管理。

设计要点：
- 所有持久化数据集中在单一数据根目录下（默认 <项目>/data），删除该目录即彻底清理。
- 配置文件原子写入（临时文件 + replace），避免断电/崩溃写坏配置。
- API Key 支持环境变量 JIGE_API_KEY 覆盖，避免明文散落。
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

from app.engine.presets import DEFAULT_PRESET, get_preset

APP_NAME = "鸡哥解题-厉不厉害你鸡哥"
APP_ID = "JiGeJieTi"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_DATA_DIR = "JIGE_DATA_DIR"
ENV_API_KEY = "JIGE_API_KEY"

# 合法的「接口协议」取值。必须与 app/engine/service.py 的 WIRE_CHOICES 一致
# （config 位于 engine 下层，反向 import 会形成循环依赖，故此处独立声明，
#  并由 tools/smoke_test.py 断言两边始终一致）。
VALID_WIRE_APIS = ("openai", "ollama_native")


def _text(value: Any) -> str:
    """把可能是脏类型的值安全地当字符串取用（脏配置比崩溃更可接受）。"""
    return value if isinstance(value, str) else ""

DETAILED_SYSTEM_PROMPT = (
    "你是大学课程解题助手。用户会给你题目文本或题目截图，请按以下要求作答：\n"
    "1. 先用一句话说明题目考查的知识点；\n"
    "2. 给出清晰的解题步骤，数学公式用 LaTeX 表示；\n"
    "3. 最后单独一行以「答案：」开头给出最终结论；\n"
    "4. 若图片模糊或题干信息不全，直接指出缺少哪些条件，禁止编造题干中不存在的数据。"
)

# 简答模式的提示词刻意写得「反过程」：模型一旦开始写步骤，
# 输出 token 数会翻好几倍，而生成时间是线性于输出长度的（实测主要瓶颈就在这里）。
BRIEF_SYSTEM_PROMPT = (
    "你是解题助手。用户会给你题目文本或题目截图。\n"
    "只给最终结果，不要写解题过程、不要解释原理、不要复述题干。\n"
    "1. 直接以「答案：」开头给出结果，整个回答不超过两行；\n"
    "2. 结果是多解时，全部并列写在同一行，用逗号分隔；\n"
    "3. 数学公式用 LaTeX 表示，能一行写完就绝不换行；\n"
    "4. 若题干信息不足，只回「题干信息不足：缺少 XXX」一句，禁止编造。"
)

# 解答风格：brief = 只看答案，detailed = 详细题解。
ANSWER_STYLES = ("brief", "detailed")
DEFAULT_ANSWER_STYLE = "detailed"
ANSWER_STYLE_LABELS = {"brief": "只看答案", "detailed": "详细题解"}
ANSWER_STYLE_PROMPTS = {
    "brief": BRIEF_SYSTEM_PROMPT,
    "detailed": DETAILED_SYSTEM_PROMPT,
}
# 简答模式的输出上限：答案通常几十个 token，512 足够且能兜住「模型开始啰嗦」的情况。
ANSWER_STYLE_MAX_TOKENS = {"brief": 512, "detailed": 0}  # 0 = 用用户配置的 max_tokens

# 兼容旧名字（早期版本只叫 DEFAULT_SYSTEM_PROMPT）
DEFAULT_SYSTEM_PROMPT = DETAILED_SYSTEM_PROMPT

# 本机 Ollama 的模型驻留时长。Ollama 自带的 5 分钟太短：冷启动要重新把模型读进显存，
# 实测 9B 模型约 70-90 秒，而热态只要 5-15 秒 —— 这个差距比任何参数调优都大。
DEFAULT_KEEP_ALIVE = "30m"
# 设置页可选的驻留时长（值需是 Ollama 认识的字符串或秒数）
KEEP_ALIVE_CHOICES = [
    ("5m", "5 分钟（Ollama 默认，最省显存）"),
    ("30m", "30 分钟（推荐）"),
    ("2h", "2 小时"),
    ("-1", "常驻不卸载（最省时间，一直占显存）"),
]


@dataclass
class EngineConfig:
    provider: str = DEFAULT_PRESET
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    # 留空表示「由服务商预设填充」：openai = OpenAI 兼容，ollama_native = Ollama 原生。
    # 这里必须留空，否则非空默认值会把预设里的 wire_api 挡掉（曾因此让 Ollama 默认走了不可用的兼容端点）。
    wire_api: str = ""
    temperature: float = 0.2
    max_tokens: int = 2048
    extra_body: str = ""  # 额外请求参数（JSON 对象），用于适配各家私有开关
    timeout: int = 180
    # 解答风格：brief = 只看答案（快），detailed = 详细题解。见 ANSWER_STYLES。
    answer_style: str = DEFAULT_ANSWER_STYLE
    # 系统提示词：**留空表示「按所选风格用内置提示词」**；填了就完全覆盖风格。
    # 这样「风格下拉」与「自定义提示词」不会互相打架：用户不动它就是纯风格切换。
    system_prompt: str = ""
    # 仅本机 Ollama 生效：模型在显存里的驻留时长。默认 5 分钟会让模型反复卸载，
    # 冷启动实测要 ~74s，热态只要 ~5-12s，所以这里默认延长到 30 分钟。
    keep_alive: str = DEFAULT_KEEP_ALIVE

    def __post_init__(self) -> None:
        # 重要：_build() 会把 config.json 里的原始值直接传给构造函数，而类型纠正
        # （_coerce_types）是在**构造之后**才跑的。所以这里必须先把本方法要用到的字段
        # 类型摆正，否则脏配置（例如 "answer_style": 5）会让下面的 .strip() 直接抛
        # AttributeError，程序连启动都起不来。
        if not isinstance(self.answer_style, str):
            self.answer_style = DEFAULT_ANSWER_STYLE
        if not isinstance(self.system_prompt, str):
            self.system_prompt = ""
        if not isinstance(self.keep_alive, str):
            self.keep_alive = DEFAULT_KEEP_ALIVE
        self.apply_preset_defaults()

    def apply_preset_defaults(self) -> None:
        """用预设补全空白字段（不覆盖用户已填内容）。"""
        p = get_preset(self.provider)
        if not self.base_url:
            self.base_url = p["base_url"]
        if not self.model:
            self.model = p["model"]
        preset_wire = p.get("wire_api", "")
        if not self.wire_api:
            self.wire_api = preset_wire
        elif self.wire_api not in VALID_WIRE_APIS:
            # 手改 config.json 把协议名写错时，引擎会静默落回「OpenAI 兼容」分支。
            # 对本机 Ollama 上的思考型模型，那条路径恰恰会返回空答案，且极难排查
            # ——所以这里直接纠正回预设值，宁可「不听从」也不「静默降级」。
            # （对比：extra_body 写坏不是静默降级，会抛中文错误，故不在此纠正。）
            self.wire_api = preset_wire
        if not self.extra_body:
            self.extra_body = p.get("extra_body", "")
        if (self.answer_style or "").strip().lower() not in ANSWER_STYLES:
            # 非法风格值同样会静默改变行为（回落成 detailed 却没人知道），所以纠正。
            self.answer_style = DEFAULT_ANSWER_STYLE
        else:
            self.answer_style = self.answer_style.strip().lower()
        # 老版本把「详细提示词全文」直接存进了 system_prompt（那是当时的默认值）。
        # 现在语义变成「留空=按风格自动」，所以把等于旧默认值的存量归一化掉，
        # 否则它会变成「自定义提示词」，把风格切换彻底挡掉。
        if self.system_prompt.strip() == DETAILED_SYSTEM_PROMPT.strip():
            self.system_prompt = ""

    # ------------------------------------------------------------ 风格解析

    @property
    def style(self) -> str:
        s = _text(self.answer_style).strip().lower()
        return s if s in ANSWER_STYLES else DEFAULT_ANSWER_STYLE

    @property
    def has_custom_prompt(self) -> bool:
        return bool(_text(self.system_prompt).strip())

    def resolved_system_prompt(self) -> str:
        """实际发给模型的系统提示词：自定义优先，否则按风格取内置。"""
        custom = _text(self.system_prompt).strip()
        if custom:
            return custom
        return ANSWER_STYLE_PROMPTS.get(self.style, DETAILED_SYSTEM_PROMPT)

    def resolved_max_tokens(self) -> int:
        """实际输出上限（0 表示不限制）。简答模式会封顶，避免模型啰嗦。"""
        try:
            configured = int(self.max_tokens)
        except (TypeError, ValueError):
            configured = 0
        cap = ANSWER_STYLE_MAX_TOKENS.get(self.style, 0)
        if cap and (configured <= 0 or configured > cap):
            return cap
        return configured

    def resolved_keep_alive(self) -> str:
        """实际发送的模型驻留时长；空串表示不带这个字段。"""
        return _text(self.keep_alive).strip()

    @property
    def vision(self) -> bool:
        return bool(get_preset(self.provider).get("vision", True))

    @property
    def need_key(self) -> bool:
        return bool(get_preset(self.provider).get("need_key", True))


@dataclass
class HotkeyConfig:
    capture: str = "<ctrl>+<alt>+q"  # 必须用 pynput 规范格式（带尖括号）
    enabled: bool = True


@dataclass
class CaptureConfig:
    mode: str = "region"  # region | fullscreen
    shot_max_width: int = 1600
    jpeg_quality: int = 88


@dataclass
class UIConfig:
    opacity: float = 0.97
    always_on_top: bool = True
    collapsed: bool = False
    pos_x: int = -1
    pos_y: int = -1
    font_size: int = 12
    last_tab: int = 0


@dataclass
class StorageConfig:
    history_limit: int = 500
    auto_trim: bool = True
    drop_orphan_shots: bool = True


@dataclass
class AppConfig:
    engine: EngineConfig = field(default_factory=EngineConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)


# ---------------------------------------------------------------- 目录管理


def data_dir() -> Path:
    """数据根目录：环境变量 > 项目内 data/。"""
    env = os.environ.get(ENV_DATA_DIR, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return PROJECT_ROOT / "data"


def ensure_dirs() -> dict[str, Path]:
    root = data_dir()
    dirs = {
        "root": root,
        "shots": root / "shots",
        "logs": root / "logs",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


def config_path() -> Path:
    return data_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "app.db"


def shots_dir() -> Path:
    return data_dir() / "shots"


def logs_dir() -> Path:
    return data_dir() / "logs"


# ---------------------------------------------------------------- 序列化


def _build(cls: type, data: Any):
    """按 dataclass 结构构建，忽略未知字段，缺失字段用默认值。"""
    if not isinstance(data, dict):
        return cls()
    # 注意：文件使用了 `from __future__ import annotations`，f.type 是字符串，
    # 必须用 get_type_hints 解析为真实类型，否则嵌套结构判断会失效。
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        real_type = hints.get(f.name, f.type)
        if is_dataclass(real_type) and isinstance(value, dict):
            kwargs[f.name] = _build(real_type, value)
        else:
            kwargs[f.name] = value
    return cls(**kwargs)


_SECTIONS = ("engine", "hotkey", "capture", "ui", "storage")


def _coerce_types(cfg: AppConfig) -> None:
    """把 JSON 中的错误类型纠正回声明类型，避免脏配置导致崩溃。"""
    defaults = AppConfig()
    for section_name in _SECTIONS:
        obj = getattr(cfg, section_name)
        dflt = getattr(defaults, section_name)
        for f in fields(obj):
            current = getattr(obj, f.name)
            default = getattr(dflt, f.name)
            try:
                if isinstance(default, bool):
                    setattr(obj, f.name, bool(current))
                elif isinstance(default, int):
                    setattr(obj, f.name, int(current))
                elif isinstance(default, float):
                    setattr(obj, f.name, float(current))
                elif isinstance(default, str) and not isinstance(current, str):
                    # 字符串字段被写成了数字/对象等，回落默认值
                    setattr(obj, f.name, default)
            except (TypeError, ValueError):
                setattr(obj, f.name, default)


class ConfigManager:
    """配置管理器：线程安全的读改写。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config_path()
        self._lock = threading.RLock()
        self._config = AppConfig()
        self.load()

    # -------------------------------------------------- 属性

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def path(self) -> Path:
        return self._path

    # -------------------------------------------------- 读写

    def load(self) -> AppConfig:
        with self._lock:
            raw: dict = {}
            if self._path.exists():
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raw = {}
            cfg = _build(AppConfig, raw)
            _coerce_types(cfg)
            cfg.engine.api_key = self.effective_api_key(cfg.engine.api_key)
            cfg.engine.apply_preset_defaults()
            self._config = cfg
            return cfg

    def save(self) -> None:
        """原子写入，避免写一半崩溃导致配置损坏。"""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = asdict(self._config)
            # 环境变量提供 key 时不落盘，避免明文泄露
            if os.environ.get(ENV_API_KEY, "").strip():
                payload["engine"]["api_key"] = ""
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self._path)

    def update(self) -> None:
        with self._lock:
            self.save()

    @staticmethod
    def effective_api_key(stored: str) -> str:
        env = os.environ.get(ENV_API_KEY, "").strip()
        return env or (stored or "").strip()

    def apply_provider(self, provider: str, *, keep_key: bool = True) -> None:
        """切换服务商：套用预设默认值。"""
        with self._lock:
            p = get_preset(provider)
            self._config.engine.provider = provider
            self._config.engine.base_url = p["base_url"]
            self._config.engine.model = p["model"]
            self._config.engine.wire_api = p["wire_api"]
            self._config.engine.extra_body = p.get("extra_body", "")
            if not keep_key:
                self._config.engine.api_key = ""
            self.save()
