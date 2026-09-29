"""核心逻辑冒烟测试：不依赖网络与图形界面。

覆盖：配置读写与脏数据纠正、存储层双向对账（无孤儿文件）、
引擎请求体构造、热键转换、LaTeX 美化。

用法：<项目>/.venv/Scripts/python.exe tools/smoke_test.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    line = f"[{mark}] {name}"
    if detail and not cond:
        line += f" -> {detail}"
    print(line)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="jige-smoke-"))
    try:
        # ---------------------------------------------------------- 配置
        section("配置层")
        from app.config import AppConfig, ConfigManager, _build, _coerce_types

        cfg_file = tmp / "config.json"
        cm = ConfigManager(cfg_file)
        check("默认配置生成", cm.config.engine.provider == "ollama")
        check("预设自动补全 base_url", bool(cm.config.engine.base_url))
        check("预设自动补全 model", bool(cm.config.engine.model))

        cm.config.engine.model = "qwen2.5vl:7b"
        cm.config.ui.opacity = 0.9
        cm.save()
        check("配置文件落盘", cfg_file.exists())

        cm2 = ConfigManager(cfg_file)
        check("配置回读一致", cm2.config.engine.model == "qwen2.5vl:7b")
        check("浮点回读一致", abs(cm2.config.ui.opacity - 0.9) < 1e-6)

        cfg_file.write_text(
            json.dumps({"engine": {"provider": "ollama", "max_tokens": "not-a-number"}},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        cm3 = ConfigManager(cfg_file)
        check("脏数据不崩溃", isinstance(cm3.config.engine.max_tokens, int),
              f"得到 {type(cm3.config.engine.max_tokens)}")

        nested = _build(AppConfig, {"engine": {"provider": "zhipu"}})
        check("嵌套 dataclass 正确构建", nested.engine.provider == "zhipu"
              and nested.engine.model == "glm-4v-flash",
              f"provider={nested.engine.provider} model={nested.engine.model}")

        # 手改 config.json 把「接口协议」写错：若不纠正，引擎会静默落回
        # 「OpenAI 兼容」分支，而本机 Ollama 的思考型模型恰好在那条路径上返回空答案，
        # 且完全没有报错 —— 这是本工程最贵的一个坑，必须有兜底。
        cfg_file.write_text(
            json.dumps({"engine": {"provider": "ollama", "wire_api": "opanai-typo"}},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        cm_bad_wire = ConfigManager(cfg_file)
        check("非法 wire_api 被纠正回预设（防静默降级为空答案）",
              cm_bad_wire.config.engine.wire_api == "ollama_native",
              f"得到 {cm_bad_wire.config.engine.wire_api!r}")

        cfg_file.write_text(
            json.dumps({"engine": {"provider": "deepseek", "wire_api": "nope"}},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        cm_bad_wire2 = ConfigManager(cfg_file)
        check("纠正目标跟随服务商预设", cm_bad_wire2.config.engine.wire_api == "openai",
              f"得到 {cm_bad_wire2.config.engine.wire_api!r}")

        from app.config import VALID_WIRE_APIS
        from app.engine.service import WIRE_CHOICES
        check("VALID_WIRE_APIS 与引擎 WIRE_CHOICES 始终一致",
              tuple(k for k, _ in WIRE_CHOICES) == tuple(VALID_WIRE_APIS),
              f"config={VALID_WIRE_APIS} engine={[k for k, _ in WIRE_CHOICES]}")

        # 对比：extra_body 写坏不做静默纠正，而是抛出可读中文错误（fail-loud 优于静默）
        cm_bad_body = ConfigManager(tmp / "c3.json")
        cm_bad_body.config.engine.extra_body = "{坏 JSON"
        from app.engine.base import EngineError, parse_extra_body
        try:
            parse_extra_body(cm_bad_body.config.engine.extra_body)
            check("extra_body 写坏时报中文错误（不静默忽略）", False, "竟然没抛异常")
        except EngineError as e:
            check("extra_body 写坏时报中文错误（不静默忽略）",
                  "不是合法 JSON" in str(e), str(e)[:80])

        cm4 = ConfigManager(tmp / "c2.json")
        cm4.apply_provider("deepseek")
        check("切换服务商套用预设", cm4.config.engine.base_url.startswith("https://api.deepseek.com"))
        # 还原，避免影响后续用例
        cm4.apply_provider("ollama")

        # ---------------------------------------------------------- 解答风格
        section("解答风格（只看答案 / 详细题解）")
        from app.config import (
            ANSWER_STYLE_LABELS,
            ANSWER_STYLE_MAX_TOKENS,
            ANSWER_STYLES,
            DEFAULT_ANSWER_STYLE,
            DETAILED_SYSTEM_PROMPT,
            EngineConfig,
        )

        check("风格取值与中文名一一对应",
              set(ANSWER_STYLES) == set(ANSWER_STYLE_LABELS),
              f"{ANSWER_STYLES} vs {list(ANSWER_STYLE_LABELS)}")
        check("默认风格为详细题解", EngineConfig(provider="ollama").style == DEFAULT_ANSWER_STYLE)

        e_brief = EngineConfig(provider="ollama", answer_style="brief")
        e_det = EngineConfig(provider="ollama", answer_style="detailed")
        check("简答与详解使用不同的内置提示词",
              e_brief.resolved_system_prompt() != e_det.resolved_system_prompt())
        check("简答提示词明确要求不给过程",
              "只给最终结果" in e_brief.resolved_system_prompt())
        check("详解提示词仍要求给出步骤",
              "解题步骤" in e_det.resolved_system_prompt())
        check("简答输出被封顶（这是它快的主因）",
              e_brief.resolved_max_tokens() == ANSWER_STYLE_MAX_TOKENS["brief"],
              f"得到 {e_brief.resolved_max_tokens()}")
        check("详解沿用用户配置的最大输出",
              e_det.resolved_max_tokens() == e_det.max_tokens,
              f"得到 {e_det.resolved_max_tokens()} vs {e_det.max_tokens}")
        e_small = EngineConfig(provider="ollama", answer_style="brief", max_tokens=128)
        check("用户把上限设得更小时尊重用户",
              e_small.resolved_max_tokens() == 128, f"得到 {e_small.resolved_max_tokens()}")

        e_custom = EngineConfig(provider="ollama", answer_style="brief",
                                system_prompt="我自己写的提示词")
        check("自定义提示词优先级高于风格开关",
              e_custom.resolved_system_prompt() == "我自己写的提示词")
        check("has_custom_prompt 能识别自定义", e_custom.has_custom_prompt)
        check("未自定义时不误报", not e_det.has_custom_prompt)

        e_bad_style = EngineConfig(provider="ollama", answer_style="胡说")
        check("非法风格值被纠正回默认（防静默回落）",
              e_bad_style.answer_style == DEFAULT_ANSWER_STYLE, f"得到 {e_bad_style.answer_style!r}")

        # 老版本把「详细提示词全文」存进了 system_prompt，迁移后必须变回「留空=按风格自动」，
        # 否则它会变成自定义提示词，把风格开关彻底挡死。
        cfg_file.write_text(
            json.dumps({"engine": {"provider": "ollama", "system_prompt": DETAILED_SYSTEM_PROMPT,
                                   "answer_style": "brief"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        cm_legacy = ConfigManager(cfg_file)
        check("旧版提示词全文被归一化为空（风格开关恢复可用）",
              cm_legacy.config.engine.system_prompt == "",
              f"得到 {cm_legacy.config.engine.system_prompt[:20]!r}…")
        check("迁移后风格仍按用户所选生效",
              "只给最终结果" in cm_legacy.config.engine.resolved_system_prompt())

        # 脏类型必须不崩：_build() 把 JSON 原值直接传给构造函数，而类型纠正（_coerce_types）
        # 是在构造之后才跑的 —— __post_init__ 里对非字符串调用 .strip() 会让程序起不来。
        from app.config import DEFAULT_KEEP_ALIVE

        cfg_file.write_text(
            json.dumps({"engine": {"provider": "ollama", "answer_style": 5,
                                   "system_prompt": 123, "keep_alive": ["30m"]}},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        cm_dirty = ConfigManager(cfg_file)
        e_dirty = cm_dirty.config.engine
        check("风格/提示词/驻留字段的脏类型被纠正且不崩溃",
              e_dirty.answer_style == DEFAULT_ANSWER_STYLE
              and e_dirty.system_prompt == ""
              and e_dirty.keep_alive == DEFAULT_KEEP_ALIVE,
              f"{e_dirty.answer_style!r} {e_dirty.system_prompt!r} {e_dirty.keep_alive!r}")
        check("脏类型下仍能解析出提示词",
              "解题步骤" in e_dirty.resolved_system_prompt())
        check("脏类型下输出上限仍可解析",
              e_dirty.resolved_max_tokens() > 0, str(e_dirty.resolved_max_tokens()))

        # ---------------------------------------------------------- 模型驻留
        section("模型驻留时长（避免反复冷启动）")
        from app.config import DEFAULT_KEEP_ALIVE, KEEP_ALIVE_CHOICES
        from app.engine.base import SolveRequest as _SR
        from app.engine.service import build_provider as _bp

        check("默认驻留时长已从 Ollama 的 5 分钟延长",
              EngineConfig(provider="ollama").keep_alive == DEFAULT_KEEP_ALIVE)
        check("驻留时长选项含「常驻不卸载」",
              any(v == "-1" for v, _ in KEEP_ALIVE_CHOICES), str(KEEP_ALIVE_CHOICES))

        nat_body = _bp(EngineConfig(provider="ollama")).payload(_SR(question="1+1"))
        check("原生协议会带 keep_alive", nat_body.get("keep_alive") == DEFAULT_KEEP_ALIVE,
              str(nat_body.get("keep_alive")))
        oai_body = _bp(EngineConfig(provider="ollama", wire_api="openai")).payload(_SR(question="1+1"))
        check("OpenAI 兼容端点不带 keep_alive（非标准字段，会被网关拒绝）",
              "keep_alive" not in oai_body)
        check("留空则不发送 keep_alive",
              "keep_alive" not in _bp(EngineConfig(provider="ollama", keep_alive="")).payload(_SR(question="x")))

        # ---------------------------------------------------------- 模型预热
        section("启动预热（不发 prompt、不产生 token）")
        from app.engine import service as _svc

        class _FakePreloadClient:
            def __init__(self, status: int = 200) -> None:
                self.status = status
                self.calls: list[tuple[str, dict]] = []

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def post(self, url, json=None, timeout=None):
                self.calls.append((url, json or {}))

                class _R:
                    status_code = self.status

                return _R()

        _real_make_client = _svc.make_client
        try:
            ok_client = _FakePreloadClient(200)
            _svc.make_client = lambda cfg: ok_client
            reason = _svc.preload_local_model(EngineConfig(provider="ollama"))
            check("预热成功返回空串", reason == "", reason)
            check("预热只打 /api/generate 一个接口",
                  len(ok_client.calls) == 1 and ok_client.calls[0][0].endswith("/api/generate"),
                  str([c[0] for c in ok_client.calls]))
            check("预热请求不带 prompt（否则会白跑一次生成）",
                  "prompt" not in ok_client.calls[0][1] and "messages" not in ok_client.calls[0][1],
                  str(ok_client.calls[0][1].keys()))
            check("预热请求带上驻留时长",
                  ok_client.calls[0][1].get("keep_alive") == DEFAULT_KEEP_ALIVE,
                  str(ok_client.calls[0][1]))

            bad_client = _FakePreloadClient(404)
            _svc.make_client = lambda cfg: bad_client
            msg = _svc.preload_local_model(EngineConfig(provider="ollama"))
            check("模型没装时预热给出可执行的中文提示（不是一句 HTTP 404）",
                  "不存在" in msg and "检测本机模型" in msg, msg)
            check("预热失败不抛异常（优化项不能阻塞启动）", isinstance(msg, str) and bool(msg))

            _svc.make_client = lambda cfg: _FakePreloadClient(500)
            check("其它 HTTP 错误也被吞成一句说明",
                  "HTTP 500" in _svc.preload_local_model(EngineConfig(provider="ollama")))

            _svc.make_client = lambda cfg: _FakePreloadClient(200)
            check("云端服务不做预热（省一次计费请求）",
                  "非本机服务" in _svc.preload_local_model(EngineConfig(provider="dashscope")))
        finally:
            _svc.make_client = _real_make_client


        # ---------------------------------------------------------- 存储
        section("存储层（无孤儿文件）")
        from app.store import Store

        data_root = tmp / "data"
        shots = data_root / "shots"
        shots.mkdir(parents=True)
        store = Store(db_file=data_root / "app.db", shots=shots)

        rel1 = store.save_shot(b"\x89PNG\r\n\x1a\n-fake-png-1")
        rid1 = store.add_record(source="image", question="截图题", image_path=rel1, answer="答案1")
        check("写入截图 + 记录", rid1 > 0 and (data_root / rel1).exists())

        # 风格要落库：否则历史页无法区分这条记录是「只看答案」还是「详细题解」
        rid_brief = store.add_record(source="text", question="简答题", answer="答案：3", style="brief")
        rid_default = store.add_record(source="text", question="默认题", answer="答案：4")
        check("记录写入风格字段",
              store.get_record(rid_brief)["style"] == "brief",
              str(store.get_record(rid_brief)))
        check("不传风格时用默认值",
              store.get_record(rid_default)["style"] == DEFAULT_ANSWER_STYLE)
        rid_blank = store.add_record(source="text", question="空风格", style="")
        check("风格为空时兜底成默认值",
              store.get_record(rid_blank)["style"] == DEFAULT_ANSWER_STYLE)
        store.delete_records([rid_brief, rid_default, rid_blank])

        # 孤儿文件：磁盘有、数据库无
        orphan = shots / "orphan-999.png"
        orphan.write_bytes(b"orphan")
        # 失效引用：数据库有、磁盘无
        rid2 = store.add_record(source="image", question="丢图题", image_path="shots/missing.png")

        res = store.reconcile()
        check("删除孤儿图片", res["orphan_deleted"] == 1, str(res))
        check("孤儿文件已消失", not orphan.exists())
        check("清理失效引用", res["dangling_cleared"] == 1, str(res))
        rec2 = store.get_record(rid2)
        check("失效引用被置空且保留记录", rec2 is not None and not rec2["image_path"])
        check("正常记录未被误删", (data_root / rel1).exists())

        # 重复对账应当幂等
        res2 = store.reconcile()
        check("对账幂等", res2["orphan_deleted"] == 0 and res2["dangling_cleared"] == 0, str(res2))

        # 越界路径防护
        store.add_record(source="image", question="越界", image_path="../../evil.png")
        check("越界路径被拒绝", store.abs_shot_path("../../evil.png") is None)

        # 删除记录连带删图
        store.delete_records([rid1])
        check("删记录连带删截图", not (data_root / rel1).exists())
        check("记录数正确", store.count_records() == 2, str(store.count_records()))

        # 历史上限裁剪
        for i in range(5):
            store.add_record(source="text", question=f"题{i}", answer=f"答{i}")
        trimmed = store.trim_history(3)
        check("超出上限被裁剪", trimmed == 4, f"trimmed={trimmed}")
        check("裁剪后剩余 3 条", store.count_records() == 3, str(store.count_records()))

        # 检索
        hits = store.list_records(keyword="题4")
        check("关键字检索命中题干", len(hits) == 1 and hits[0]["question"] == "题4", str(hits))

        # 全清
        cleared = store.clear_all()
        check("一键清空记录与文件", cleared["records"] == 3 and store.count_records() == 0, str(cleared))
        left = [p for p in shots.glob("*") if p.is_file()]
        check("清空后截图目录无残留文件", not left, str(left))

        stats = store.stats()
        check("统计接口可用", set(stats) == {"records", "files", "bytes"}, str(stats))
        store.close()

        # 老库升级：手工建一张没有 style 列的旧表，Store 打开时应自动补列且旧数据可读。
        # （CREATE TABLE IF NOT EXISTS 不会给已有表补列，漏掉迁移就是线上崩）
        import sqlite3 as _sqlite3

        legacy_dir = tmp / "legacy"
        legacy_dir.mkdir()
        legacy_db = legacy_dir / "app.db"
        raw = _sqlite3.connect(str(legacy_db))
        raw.executescript(
            "CREATE TABLE records ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, source TEXT NOT NULL,"
            " question TEXT NOT NULL DEFAULT '', image_path TEXT, answer TEXT NOT NULL DEFAULT '',"
            " provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',"
            " status TEXT NOT NULL DEFAULT 'ok', error TEXT NOT NULL DEFAULT '',"
            " elapsed_ms INTEGER NOT NULL DEFAULT 0);"
        )
        raw.execute(
            "INSERT INTO records (created_at, source, question, answer) VALUES ('2026-01-01T00:00:00','text','老记录','老答案')"
        )
        raw.commit()
        raw.close()

        legacy_shots = legacy_dir / "shots"
        legacy_shots.mkdir()
        legacy_store = Store(db_file=legacy_db, shots=legacy_shots)
        old_rows = legacy_store.list_records()
        check("老库自动补出 style 列", len(old_rows) == 1 and "style" in old_rows[0], str(old_rows))
        check("老数据回落到「详细题解」", old_rows[0]["style"] == DEFAULT_ANSWER_STYLE,
              str(old_rows[0].get("style")))
        legacy_store.add_record(source="text", question="新记录", style="brief")
        check("迁移后新写入带风格",
              legacy_store.list_records()[0]["style"] == "brief")
        legacy_store.close()

        # ---------------------------------------------------------- 引擎
        section("引擎层（离线构造请求体）")
        from app.config import EngineConfig
        from app.engine.base import SolveRequest, _is_local
        from app.engine.service import build_provider

        # --- 默认：本机 Ollama 走原生协议，并默认关闭思考模式 ---
        # 背景：Ollama 的 OpenAI 兼容端点(/v1)对 thinking 模型会返回空内容
        # （输出预算被内部推理吃光），必须走原生 /api/chat 且 think=false。
        cfg = EngineConfig(provider="ollama")
        cfg.api_key = ""
        cfg.apply_preset_defaults()
        p = build_provider(cfg)
        check("Ollama 默认走原生协议端点",
              p.url() == "http://127.0.0.1:11434/api/chat", p.url())

        body = p.payload(SolveRequest(question="1+1=?"), stream=True)
        check("纯文本请求体结构", body["messages"][-1]["content"] == "1+1=?" and body["stream"] is True)
        check("系统提示已注入", body["messages"][0]["role"] == "system")
        check("Ollama 默认已关闭思考模式（防空答案）", body.get("think") is False, str(body.get("think")))

        img_body = p.payload(SolveRequest(question="看题", image_b64="QUJD", image_mime="image/jpeg"), stream=True)
        check("原生协议 images 字段", img_body["messages"][-1]["images"] == ["QUJD"])
        check("原生协议 options.num_predict", "num_predict" in img_body["options"])
        check("原生协议 content 仍为字符串",
              isinstance(img_body["messages"][-1]["content"], str),
              type(img_body["messages"][-1]["content"]).__name__)

        # --- 显式指定时仍可走 OpenAI 兼容端点（多模态数组格式） ---
        cfg_oai = EngineConfig(provider="ollama", wire_api="openai")
        cfg_oai.apply_preset_defaults()
        po = build_provider(cfg_oai)
        check("显式 openai 走 /v1/chat/completions",
              po.url() == "http://127.0.0.1:11434/v1/chat/completions", po.url())
        ob = po.payload(SolveRequest(question="看题", image_b64="QUJD", image_mime="image/jpeg"), stream=True)
        content = ob["messages"][-1]["content"]
        check("兼容端点图片为多模态数组", isinstance(content, list) and len(content) == 2, str(content)[:120])
        check("图片走 data url",
              content[1]["image_url"]["url"] == "data:image/jpeg;base64,QUJD",
              content[1]["image_url"]["url"][:40])

        # 缺 key 的校验
        from app.engine.base import EngineError

        cfg_key = EngineConfig(provider="dashscope")
        cfg_key.apply_preset_defaults()
        cfg_key.api_key = ""
        try:
            build_provider(cfg_key).validate()
            ok = False
        except EngineError as e:
            ok = "API Key" in str(e)
        check("缺 Key 时给出可读提示", ok)

        check("本地地址识别", _is_local("http://127.0.0.1:11434/v1") and not _is_local("https://api.openai.com/v1"))

        # ---------------------------------------------------------- 模型探测
        section("模型探测与「模型没装」提前拦截")
        from app.engine import base as ebase

        class _FakeResp:
            def __init__(self, payload: dict, status: int = 200) -> None:
                self._payload = payload
                self.status_code = status

            def json(self) -> dict:
                return self._payload

        class _FakeClient:
            def __init__(self, payload: dict, status: int = 200) -> None:
                self._payload = payload
                self._status = status
                self.calls: list[str] = []

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, headers=None):
                self.calls.append(url)
                return _FakeResp(self._payload, self._status)

        _real_make_client = ebase.make_client
        try:
            fake = _FakeClient({"models": [{"name": "qwen3.5:9b"}, {"name": "qwen2.5vl:7b"}]})
            ebase.make_client = lambda cfg: fake
            cfg_local = EngineConfig(provider="ollama")
            cfg_local.apply_preset_defaults()
            got = ebase.detect_models(cfg_local)
            check("探测本机模型列表（/api/tags）", got == ["qwen2.5vl:7b", "qwen3.5:9b"], str(got))
            check("本机探测优先走 /api/tags", fake.calls[0].endswith("/api/tags"), str(fake.calls))

            fake2 = _FakeClient({"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})
            ebase.make_client = lambda cfg: fake2
            cfg_cloud = EngineConfig(provider="deepseek")
            cfg_cloud.apply_preset_defaults()
            cfg_cloud.api_key = "sk-test"
            got2 = ebase.detect_models(cfg_cloud)
            check("探测云端模型列表（/v1/models）",
                  got2 == ["deepseek-chat", "deepseek-reasoner"], str(got2))

            ebase.make_client = lambda cfg: _FakeClient({"models": [{"name": "qwen3.5:9b"}]})
            cfg_missing = EngineConfig(provider="ollama")
            cfg_missing.apply_preset_defaults()
            cfg_missing.model = "qwen2.5vl:7b"  # 本机没装
            msg = build_provider(cfg_missing)._preflight_model()
            check("未安装的模型被提前拦下",
                  "没有找到模型" in msg and "qwen3.5:9b" in msg and "ollama pull" in msg, msg[:90])

            cfg_ok = EngineConfig(provider="ollama")
            cfg_ok.apply_preset_defaults()
            cfg_ok.model = "qwen3.5:9b"
            check("已安装的模型直接放行", build_provider(cfg_ok)._preflight_model() == "")

            check("配置不写 tag 时认 :latest", ebase._model_matches("llama3", ["llama3:latest"]))
            check("不把 :9b 误认成无 tag 的同名模型", not ebase._model_matches("qwen3.5", ["qwen3.5:9b"]))

            hint = ebase.friendly_http_error(404, '{"error":"model not found"}', "http://127.0.0.1:11434/api/chat")
            check("模型不存在时错误信息带排查指引", "检测本机模型" in hint, hint[:90])
            plain404 = ebase.friendly_http_error(404, "not here", "https://x.test/v1")
            check("普通 404 不误加模型提示", "检测本机模型" not in plain404, plain404[:60])

            hint_txt = ebase.missing_model_hint(cfg_missing, ["qwen3.5:9b"])
            check("「模型没装」文案带稳定标识（供 UI 判断）",
                  ebase.is_missing_model_error(hint_txt), hint_txt[:50])
            check("普通报错不被误判为「模型没装」",
                  not ebase.is_missing_model_error("服务返回 HTTP 401。API Key 无效。"))
            check("空串不被误判", not ebase.is_missing_model_error(""))

            ebase.make_client = lambda cfg: _FakeClient({}, status=500)
            try:
                ebase.detect_models(cfg_local)
                check("探测失败给出中文提示", False)
            except EngineError as e:
                check("探测失败给出中文提示", "探测模型列表失败" in str(e), str(e)[:60])
        finally:
            ebase.make_client = _real_make_client

        # ---------------------------------------------------------- 热键
        section("热键转换")
        from app.hotkey import pynput_to_qt, qt_to_pynput, sequence_is_valid

        check("Ctrl+Alt+Q -> <ctrl>+<alt>+q", qt_to_pynput("Ctrl+Alt+Q") == "<ctrl>+<alt>+q",
              qt_to_pynput("Ctrl+Alt+Q"))
        check("Ctrl+Shift+F2 转换", qt_to_pynput("Ctrl+Shift+F2") == "<ctrl>+<shift>+<f2>",
              qt_to_pynput("Ctrl+Shift+F2"))
        check("反向转换显示", pynput_to_qt("<ctrl>+<alt>+q") == "Ctrl+Alt+Q",
              pynput_to_qt("<ctrl>+<alt>+q"))
        check("纯修饰键判为非法", not sequence_is_valid("Ctrl+Alt"))
        check("空串判为非法", not sequence_is_valid(""))

        # ---------------------------------------------------------- 文本美化
        section("答案美化")
        from app.ui.formatting import to_plain, to_markdown

        plain = to_plain(r"因为 $\frac{a}{b} \times \sqrt{2} \leq 10$，所以答案")
        check("分数/根号/符号转换", "a)/(b" in plain and "×" in plain and "√(2)" in plain and "≤" in plain,
              plain)
        check("去掉美元符号", "$" not in plain, plain)
        check("上标数字转换", "x²" in to_plain("x^2"), to_plain("x^2"))
        check("markdown 预处理非空", bool(to_markdown("**结论**：42")))

        # ---------------------------------------------------------- 结论
        section("结果")
        print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
        if FAIL:
            print("失败项：" + ", ".join(FAIL))
            return 1
        return 0
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
