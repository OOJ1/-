"""真机验证：全局热键注册 + 真实按键触发 + 应用启动自检。

这个脚本会：
1. 真实注册 <ctrl>+<alt>+q 全局热键，并用 SendInput 模拟按键，确认回调被触发；
2. 以干净环境启动 main.py，等几秒后确认进程存活、日志无异常，然后结束进程；
3. 校验数据目录的落点，最后清空，保证交付时是干净的。

用法：<项目>/.venv/Scripts/python.exe tools/verify_live.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PY = ROOT / ".venv" / "Scripts" / "python.exe"
PASS: list[str] = []
FAIL: list[str] = []
SKIP: list[str] = []

# 本机沙箱会在文件删除上注入守卫（报 SAFE_DELETE_BULK_CONFIRM_REQUIRED）。
# 这属于运行环境限制，不是应用留下的垃圾清不掉，所以单独识别、单独报告。
ENV_GUARD_MARKERS = ("SAFE_DELETE", "BULK_CONFIRM", "BULK_GUARD")


def _is_env_guard(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".upper()
    return any(m in text for m in ENV_GUARD_MARKERS)


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -> {detail}" if detail and not cond else ""))


def skip(name: str, reason: str) -> None:
    SKIP.append(name)
    print(f"[SKIP] {name} -> {reason}")


def clean_env() -> dict:
    """模拟用户从资源管理器启动：去掉沙箱注入的 PYTHONPATH 与代理变量。"""
    drop = {"PYTHONPATH", "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"}
    return {k: v for k, v in os.environ.items() if k not in drop}


def test_hotkey() -> None:
    print("=== 全局热键真机测试 ===")
    from PySide6.QtCore import QCoreApplication, Qt, QObject

    app = QCoreApplication([])

    from app.hotkey import HotkeyManager, display_text, normalize

    check("松散写法被归一化", normalize("ctrl+alt+q") == "<ctrl>+<alt>+q", normalize("ctrl+alt+q"))
    check("规范写法保持不变", normalize("<ctrl>+<alt>+q") == "<ctrl>+<alt>+q")
    check("界面文案友好", display_text("ctrl+alt+q") == "Ctrl+Alt+Q", display_text("ctrl+alt+q"))

    class Probe(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.hits = 0

        def on_fire(self) -> None:
            self.hits += 1

    probe = Probe()
    manager = HotkeyManager()
    errors: list[str] = []
    manager.failed.connect(errors.append)

    ok = manager.start("<ctrl>+<alt>+q")
    check("热键注册成功", ok, str(errors))
    check("监听器处于活动状态", manager.active)

    if ok:
        from pynput.keyboard import Controller, Key

        # 用 DirectConnection，避免依赖事件循环即可观测回调
        manager.triggered.connect(probe.on_fire, Qt.DirectConnection)
        keyboard = Controller()
        time.sleep(0.4)
        keyboard.press(Key.ctrl)
        keyboard.press(Key.alt)
        keyboard.press("q")
        time.sleep(0.08)
        keyboard.release("q")
        keyboard.release(Key.alt)
        keyboard.release(Key.ctrl)
        deadline = time.time() + 4
        while time.time() < deadline and probe.hits == 0:
            app.processEvents()
            time.sleep(0.05)
        check("模拟按下 Ctrl+Alt+Q 触发回调", probe.hits >= 1, f"命中 {probe.hits} 次")

    manager.stop()
    check("停止后监听器已释放", not manager.active)


def test_launch() -> None:
    print("\n=== 应用启动真机测试 ===")
    data_dir = ROOT / "data"
    log_file = data_dir / "logs" / "app.log"

    env = clean_env()
    proc = subprocess.Popen(
        [str(PY), "main.py"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        time.sleep(8)
        alive = proc.poll() is None
        check("启动后进程持续存活（未崩溃）", alive, f"退出码 {proc.returncode}")
        check("数据目录已创建", data_dir.is_dir() and (data_dir / "shots").is_dir())
        check("配置文件已生成", (data_dir / "config.json").exists())
        check("数据库已生成", (data_dir / "app.db").exists())
        check("日志文件已生成", log_file.exists())

        if log_file.exists():
            log = log_file.read_text(encoding="utf-8", errors="replace")
            check("日志中有热键注册成功记录", "全局热键已注册" in log, log[-400:])
            check("日志无 CRITICAL/未捕获异常",
                  "CRITICAL" not in log and "未捕获异常" not in log, log[-600:])

        cfg = (data_dir / "config.json").read_text(encoding="utf-8") if (data_dir / "config.json").exists() else ""
        check("默认热键为规范格式", "<ctrl>+<alt>+q" in cfg, cfg[:300])
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        out = b""
        try:
            out = proc.stdout.read() if proc.stdout else b""
        except Exception:  # noqa: BLE001
            pass
        if out.strip():
            print("--- 子进程输出 ---")
            print(out.decode("utf-8", "replace")[-1500:])
        check("进程已结束", proc.poll() is not None, str(proc.poll()))


def _unlink_retry(path: Path, attempts: int = 12) -> bool:
    """删除文件/目录，成功返回 True。

    - Windows 结束进程后句柄释放有延迟，所以需要重试几次；
    - 若撞上运行环境的删除守卫（安全沙箱），立刻放弃重试并返回 False：
      重试再多也没用，而且会把脚本拖慢几十秒。
    """
    for _ in range(attempts):
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except OSError as e:
            if _is_env_guard(e):
                return False
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001  守卫可能抛非 OSError
            if _is_env_guard(e):
                return False
            time.sleep(0.5)
    return False if path.exists() else True


def _delete_guard_active() -> tuple[bool, str]:
    """当前环境是否注入了「批量删除守卫」。

    注意这类守卫的行为很坑：删除量超过阈值时它**直接终止进程**，
    既没有异常也没有堆栈，只留下一个 exit code 1 和半截输出
    （本脚本最初就因此「静默地死在清理阶段」）。
    所以这里先探测再决定要不要删，而不是删到一半被砍。
    """
    if os.environ.get("CODEBUDDY_SAFE_DELETE_SANDBOX") == "1" or os.environ.get(
        "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR"
    ):
        return True, "检测到运行环境的批量删除守卫（CODEBUDDY_SAFE_DELETE_*）"
    return False, ""


def cleanup() -> None:
    print("\n=== 清理验证产物 ===")
    # 本脚本导入 app.logger 后会持有 data/logs/app.log，必须先释放句柄才删得掉
    import logging

    logging.shutdown()

    guarded, why = _delete_guard_active()
    if guarded:
        print(f"  ! {why}")
        print("    该守卫在删除量超阈值时会直接终止进程，因此这里不做删除尝试。")
        print("    人工清理：退出程序后删除 data\\ 与 _verify\\ 两个目录即可（不影响使用）。")
        skip("交付前 data/ 无残留文件", "沙箱删除守卫，未执行删除")
        skip("临时验证图已清理", "沙箱删除守卫，未执行删除")
        return

    data_dir = ROOT / "data"
    failed: list[str] = []
    for name in ("app.db", "app.db-wal", "app.db-shm", "app.lock", "config.json"):
        if not _unlink_retry(data_dir / name):
            failed.append(name)
    for sub in ("shots", "logs"):
        d = data_dir / sub
        if d.is_dir():
            for f in list(d.iterdir()):
                if f.is_file() and not _unlink_retry(f):
                    failed.append(f"{sub}/{f.name}")

    left = sorted(str(p.relative_to(ROOT)) for p in data_dir.rglob("*") if p.is_file()) if data_dir.exists() else []
    if failed:
        print(f"  ! {len(failed)} 个文件删除失败（外部删除守卫？）：{', '.join(left[:8])}")
    check("交付前 data/ 无残留文件", not left, str(left))

    _unlink_retry(ROOT / "_verify")
    check("临时验证图已清理", not (ROOT / "_verify").exists())


def main() -> int:
    test_hotkey()
    test_launch()
    cleanup()
    print(f"\n=== 结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项，跳过 {len(SKIP)} 项 ===")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    if SKIP:
        print("跳过项（环境限制，非应用问题）：" + ", ".join(SKIP))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
