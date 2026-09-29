"""真实模型端到端验证。

用途：确认「引擎 → 模型 → 落库 → 界面渲染」这一整条真实链路能跑通（前面的自检用的是假服务）。

行为：
1. 探测 127.0.0.1:11434；没起来就尝试拉起本机 Ollama（只在同一条命令里有效，
   沙箱会在命令结束后回收子进程，所以启动+测试必须一次跑完）；
2. 列出模型并优先挑一个 capability 含 vision 的；
3. 引擎层跑文字题 + 图片题（题干用 Qt 真实绘制成截图）；
4. 走一遍完整应用流程（FloatWindow + SolveWorker + Store），断言答案落库。

用法：<项目>/.venv/Scripts/python.exe tools/verify_real_model.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OLLAMA_API = "http://127.0.0.1:11434"
OLLAMA_EXE_CANDIDATES = [Path(r"E:\Ollama\ollama.exe"), Path(r"C:\Program Files\Ollama\ollama.exe")]

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -> {detail}" if detail and not cond else ""))


def _delete_guard_active() -> bool:
    """运行环境是否注入了「批量删除守卫」。

    这类守卫在删除量超阈值时会**直接终止进程**——没有异常、没有堆栈，
    只留一个非 0 退出码和半截输出。所以清理临时文件前必须先探测；
    命中就跳过删除，否则脚本会在最后一步静默死掉，连统计行都打不出来。
    """
    return bool(
        os.environ.get("CODEBUDDY_SAFE_DELETE_SANDBOX") == "1"
        or os.environ.get("CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR")
    )


def api_get(path: str, timeout: float = 5):
    req = urllib.request.Request(OLLAMA_API + path, method="GET")
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def server_alive() -> bool:
    try:
        api_get("/api/version", timeout=3)
        return True
    except Exception:  # noqa: BLE001
        return False


def start_ollama() -> subprocess.Popen | None:
    if server_alive():
        print("检测到 Ollama 已在运行，直接复用。")
        return None
    exe = next((p for p in OLLAMA_EXE_CANDIDATES if p.exists()), None)
    if exe is None:
        found = shutil.which("ollama")
        exe = Path(found) if found else None
    if exe is None:
        print("未找到 ollama 可执行文件，跳过本机服务启动。")
        return None
    print(f"正在启动 {exe} serve ...")
    log = ROOT / "_ollama.log"
    fh = open(log, "wb")
    proc = subprocess.Popen(
        [str(exe), "serve"], cwd=str(exe.parent), stdout=fh, stderr=subprocess.STDOUT
    )
    for _ in range(60):
        time.sleep(1)
        if server_alive():
            print(f"服务已就绪（{_} 秒）。")
            return proc
    print("服务启动超时。")
    return proc


def pick_model() -> tuple[str, list[str]]:
    data = api_get("/api/tags", timeout=10)
    models = data.get("models", [])
    if not models:
        raise RuntimeError("本机没有任何 Ollama 模型")
    print("本机模型：")
    best = None
    for m in models:
        caps = m.get("capabilities") or []
        size_gb = (m.get("size") or 0) / 1024**3
        print(f"  - {m['name']:24s} {size_gb:5.2f} GB  capabilities={caps}")
        if "vision" in caps and best is None:
            best = (m["name"], caps)
    if best is None:
        best = (models[0]["name"], models[0].get("capabilities") or [])
    return best


def main() -> int:
    proc = start_ollama()
    try:
        if not server_alive():
            print("Ollama 不可用，无法做真实模型验证。")
            return 2

        model, caps = pick_model()
        has_vision = "vision" in caps
        print(f"\n选用模型：{model}（vision={has_vision}）")

        # ---------------------------------------------------- 引擎层
        from app import capture as cap
        from app.config import EngineConfig
        from app.engine.base import SolveRequest
        from app.engine.service import build_provider
        from app.ui import theme

        # Qt 的 QFont / QPainter 必须先有 QGuiApplication 才能用，
        # 否则 Qt6 会直接把进程 abort 掉（表现为「没有异常、没有堆栈、跑到 C 段就没了」）。
        # 所以在这里就创建，D 段的悬浮窗复用同一个实例。
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        app.setFont(theme.app_font(12))
        app.setStyleSheet(theme.STYLESHEET)

        cfg = EngineConfig(provider="ollama")
        cfg.model = model
        cfg.apply_preset_defaults()
        cfg.model = model
        cfg.timeout = 600
        cfg.max_tokens = 1024

        print("\n=== A. 文字题（OpenAI 兼容协议，应用的默认路径）===")
        t0 = time.time()
        res = build_provider(cfg).solve(SolveRequest(question="求解方程 x^2 + 5x - 6 = 0 的根。"))
        dt = time.time() - t0
        print(f"耗时 {dt:.1f}s，错误={res.error!r}")
        print("答案（前 400 字）：")
        print((res.answer or "")[:400])
        check("文字题返回非空答案", bool(res.answer.strip()) and not res.error, res.error or "空答案")
        check("文字题答案包含正确根（1 与 -6）",
              "1" in res.answer and "6" in res.answer, res.answer[:120])

        print("\n=== B. 文字题（Ollama 原生协议）===")
        cfg_native = EngineConfig(provider="ollama", wire_api="ollama_native")
        cfg_native.model = model
        cfg_native.apply_preset_defaults()
        cfg_native.model = model
        cfg_native.timeout = 600
        cfg_native.max_tokens = 512
        t0 = time.time()
        res_native = build_provider(cfg_native).solve(SolveRequest(question="3 的平方是多少？只回答数字"))
        print(f"耗时 {time.time() - t0:.1f}s，答案={res_native.answer[:80]!r}，错误={res_native.error!r}")
        check("原生协议也返回非空答案", bool(res_native.answer.strip()) and not res_native.error)

        # ---------------------------------------------------- 图片题
        print("\n=== C. 图片题（真实渲染题干截图 → 视觉模型）===")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QImage, QPainter

        img = QImage(900, 240, QImage.Format_RGB32)
        img.fill(QColor("#FFFFFF"))
        painter = QPainter(img)
        painter.setPen(QColor("#111111"))
        font = theme.app_font(20)
        painter.setFont(font)
        painter.drawText(
            img.rect().adjusted(30, 20, -30, -20),
            int(Qt.AlignLeft | Qt.TextWordWrap),
            "第 3 题：已知一元二次方程 x² + 5x − 6 = 0，求它的两个根。请写出求解步骤。",
        )
        painter.end()
        png = cap.to_png_bytes(img)
        b64, mime = cap.encode_for_model(img, max_width=1200, quality=90)
        print(f"截图 {img.width()}x{img.height()} → PNG {len(png)} 字节，送模型 base64 {len(b64)} 字符")

        if not has_vision:
            print("当前模型不支持视觉，跳过图片题。")
        else:
            t0 = time.time()
            res_img = build_provider(cfg).solve(
                SolveRequest(question="请解答图片中的题目。", image_b64=b64, image_mime=mime)
            )
            print(f"耗时 {time.time() - t0:.1f}s，错误={res_img.error!r}")
            print("答案（前 400 字）：")
            print((res_img.answer or "")[:400])
            check("图片题返回非空答案", bool(res_img.answer.strip()) and not res_img.error,
                  res_img.error or "空答案")
            check("视觉模型读出了题干（答案含 1 与 6）",
                  "1" in res_img.answer and "6" in res_img.answer, res_img.answer[:150])

        # ---------------------------------------------------- 真实抓屏链路
        # 前面 C 段是「自己画一张图」送模型，绕过了真实抓屏；
        # 这里补上真正的链路：真实抓屏 → 按 scale 换算物理像素 → 框选裁切 → 送模型。
        # 为了既能断言对错、又不去抓用户屏幕上的内容，先在屏幕一角放一个
        # 「内容已知」的小窗口，再抓整个虚拟桌面，然后只把该窗口那块区域裁出来送模型。
        print("\n=== E. 真实抓屏 → 框选裁切 → 真实模型 ===")
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtWidgets import QLabel, QWidget
        from app.ui.overlay import MIN_SIZE, CaptureOverlay

        probe = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        probe.setStyleSheet("background:#FFFFFF;")
        probe.resize(760, 190)
        probe.move(80, 80)
        probe_label = QLabel("第 5 题：已知一元二次方程 x² - 7x + 12 = 0，求它的两个根。", probe)
        probe_label.setStyleSheet("background:#FFFFFF; color:#111111; font-size:26px; font-weight:600;")
        probe_label.setGeometry(20, 20, 720, 150)
        probe_label.setWordWrap(True)
        probe.show()
        probe.raise_()
        probe.activateWindow()
        for _ in range(14):  # 留时间给窗口管理器真正绘制出来
            app.processEvents()
            time.sleep(0.05)

        real_img, real_scale, real_union = cap.grab_virtual_desktop()
        print(f"抓屏：{real_img.width()}x{real_img.height()} 物理像素，scale={real_scale}，"
              f"逻辑并集={real_union.width()}x{real_union.height()}@{real_union.x()},{real_union.y()}")
        check("真实抓屏拿到非空位图", real_img.width() > 100 and real_img.height() > 100)

        # 覆盖层的坐标系是「以逻辑并集左上角为原点」，所以要减掉 union 的偏移
        probe_tl = probe.mapToGlobal(QPoint(0, 0))
        local = QRect(probe_tl - real_union.topLeft(), probe.size())
        overlay = CaptureOverlay(real_img, real_scale, real_union, mode="region")
        got: list = []
        overlay.captured.connect(lambda im: got.append(im))
        overlay._origin = local.topLeft()
        overlay._current = local.bottomRight()
        overlay._dragging = False
        # 走的是覆盖层自己的 _selection() + _emit()（含 scale→物理像素换算与越界裁剪），
        # 只是不注入全局鼠标事件（那属于 verify_live 的职责，且会动到用户的鼠标）。
        sel = overlay._selection()
        check(f"框选区域达到最小尺寸（{MIN_SIZE}px）",
              sel.width() >= MIN_SIZE and sel.height() >= MIN_SIZE, f"{sel.width()}x{sel.height()}")
        overlay._emit(sel)

        check("框选后收到裁切结果", len(got) == 1, f"收到 {len(got)} 张")
        if not got:
            print("裁切没触发，E 段后续检查跳过。")
        else:
            cropped = got[0]
            exp_w = max(1, round(local.width() * real_scale))
            exp_h = max(1, round(local.height() * real_scale))
            print(f"裁切：{cropped.width()}x{cropped.height()} 物理像素（按 scale 期望 {exp_w}x{exp_h}）")
            check("裁切尺寸按 scale 正确换算",
                  abs(cropped.width() - exp_w) <= 1 and abs(cropped.height() - exp_h) <= 1,
                  f"{cropped.width()}x{cropped.height()} vs {exp_w}x{exp_h}")
            # 内容不是一整块纯色，说明真的抓到了窗口（没抓到会是桌面/黑屏）
            colors = {cropped.pixel(x, y) for x in range(0, cropped.width(), 7)
                      for y in range(0, cropped.height(), 7)}
            check("裁切内容不是纯色（确实抓到了窗口）", len(colors) > 2, f"采样到 {len(colors)} 种颜色")

            b64_real, mime_real = cap.encode_for_model(cropped, max_width=1200, quality=90)
            t0 = time.time()
            res_real = build_provider(cfg).solve(
                SolveRequest(question="请解答图片中的题目。", image_b64=b64_real, image_mime=mime_real)
            )
            print(f"送模型 {len(b64_real)} 字符，耗时 {time.time() - t0:.1f}s，错误={res_real.error!r}")
            print("答案（前 200 字）：", (res_real.answer or "")[:200].replace("\n", " "))
            check("真实截图链路返回非空答案",
                  bool(res_real.answer.strip()) and not res_real.error, res_real.error or "空答案")
            check("模型读出了真实截图的题干（答案含 3 与 4）",
                  "3" in res_real.answer and "4" in res_real.answer, res_real.answer[:150])

        probe.close()
        probe.deleteLater()
        app.processEvents()

        # ---------------------------------------------------- 完整应用流程
        print("\n=== D. 完整应用流程（悬浮窗 + 工作线程 + 落库）===")
        tmp = Path(tempfile.mkdtemp(prefix="jige-real-"))
        os.environ["JIGE_DATA_DIR"] = str(tmp)
        # 注意：不要给 QT_QPA_PLATFORM 赋空串，否则 Qt 会找不到平台插件；
        # 这里就是要用默认的 windows 平台（离屏平台没有字体库，题干画不出中文）。

        import shutil as _sh

        from app.config import ConfigManager
        from app.store import SOURCE_IMAGE, Store
        from app.ui.float_window import FloatWindow

        # QApplication 已在前面创建好，这里直接复用（同一个进程只能有一个实例）
        cfgmgr = ConfigManager(tmp / "config.json")
        cfgmgr.config.engine.provider = "ollama"
        cfgmgr.config.engine.model = model
        cfgmgr.config.engine.base_url = OLLAMA_API + "/v1"
        cfgmgr.config.engine.timeout = 600
        cfgmgr.save()
        store = Store(db_file=tmp / "app.db", shots=tmp / "shots")

        window = FloatWindow(cfgmgr, store)
        window.show()
        app.processEvents()

        state = {"done": False}
        window.submit_image(img, png, note="第 3 题：x² + 5x − 6 = 0")
        rid = window._current_rid
        worker = window._worker
        worker.done.connect(lambda *_: state.update(done=True))
        worker.failed.connect(lambda *_: state.update(done=True))
        deadline = time.time() + 600
        while time.time() < deadline and not state["done"]:
            app.processEvents()
            time.sleep(0.05)
        check("界面流程跑完（未超时）", state["done"])

        rec = store.get_record(rid) if rid else None
        check("数据库已落库", bool(rec))
        if rec:
            print(f"记录：source={rec['source']} status={rec['status']} "
                  f"model={rec['model']} elapsed={rec['elapsed_ms']}ms "
                  f"image={rec['image_path']}")
            print("落库答案（前 300 字）：")
            print((rec["answer"] or "")[:300])
            check("落库来源为截图解题", rec["source"] == SOURCE_IMAGE)
            check("落库状态为 ok", rec["status"] == "ok", rec["error"][:200])
            check("落库答案非空", len(rec["answer"].strip()) > 10)
            check("截图文件确实存在",
                  bool(store.abs_shot_path(rec["image_path"])) and
                  store.abs_shot_path(rec["image_path"]).exists())
            check("耗时已记录", rec["elapsed_ms"] > 0, str(rec["elapsed_ms"]))

        check("界面已渲染答案", len(window.answer_view.toPlainText().strip()) > 10,
              window.answer_view.toPlainText()[:80])

        window.close()
        store.close()

        # ---------------------------------------------------- 简答 vs 详解
        print("\n=== F. 「只看答案」vs「详细题解」真实对拍 + 模型预热 ===")
        from app.engine.service import preload_local_model

        _q = "求解方程 x^2 + 5x - 6 = 0 的根。"
        timings: dict[str, tuple[float, int, str]] = {}
        for style in ("detailed", "brief"):
            c = EngineConfig(provider="ollama")
            c.model = model
            c.apply_preset_defaults()
            c.model = model
            c.timeout = 600
            c.answer_style = style
            t0 = time.time()
            r = build_provider(c).solve(SolveRequest(question=_q))
            dt = time.time() - t0
            timings[style] = (dt, len(r.answer or ""), r.answer or "")
            print(f"{style:8s} 耗时 {dt:5.1f}s  输出 {len(r.answer or ''):4d} 字  "
                  f"num_predict 上限={c.resolved_max_tokens()}")
            print(f"         答案：{(r.answer or '').strip()[:120]!r}")
            check(f"{style} 模式返回非空答案", bool((r.answer or "").strip()) and not r.error,
                  r.error or "空答案")
            check(f"{style} 模式答案含正确根（1 与 -6）",
                  "1" in (r.answer or "") and "6" in (r.answer or ""), (r.answer or "")[:120])

        d_det, n_det, _ = timings["detailed"]
        d_brief, n_brief, brief_ans = timings["brief"]
        check("「只看答案」输出确实更短", n_brief < n_det, f"{n_brief} vs {n_det}")
        check("「只看答案」确实更快", d_brief < d_det, f"{d_brief:.1f}s vs {d_det:.1f}s")
        # 简答要的是「一句话就能看懂」，这里顺带守住质量：不能因为短就变成空话。
        check("「只看答案」答案里直接写了结论", "答案" in brief_ans or "=" in brief_ans,
              brief_ans[:120])

        t0 = time.time()
        reason = preload_local_model(cfg)
        print(f"预热（不发 prompt，只让 Ollama 把权重读进显存）：耗时 {time.time() - t0:.1f}s，{reason or 'OK'}")
        check("模型预热调用成功", reason == "", reason)

        if _delete_guard_active():
            print(f"（运行环境有删除守卫，临时目录保留：{tmp}）")
        else:
            _sh.rmtree(tmp, ignore_errors=True)

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not _delete_guard_active():
            for junk in ("_req.json", "_resp.json", "_r1.json", "_ollama.log"):
                (ROOT / junk).unlink(missing_ok=True)

    print(f"\n=== 结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项 ===")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
