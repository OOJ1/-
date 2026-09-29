"""全局热键：pynput 用户态键盘钩子（Windows 下无需管理员权限）。

线程模型：pynput 监听线程只负责 emit Qt 信号，绝不直接碰界面对象，
Qt 的跨线程信号是队列投递的，天然安全。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence

from app.logger import get

log = get("hotkey")

_MOD_MAP = {
    "ctrl": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
    "meta": "<cmd>",
    "win": "<cmd>",
}

_SPECIAL = {
    "space": "<space>",
    "return": "<enter>",
    "enter": "<enter>",
    "tab": "<tab>",
    "esc": "<esc>",
    "escape": "<esc>",
    "backspace": "<backspace>",
    "del": "<delete>",
    "delete": "<delete>",
    "ins": "<insert>",
    "insert": "<insert>",
    "home": "<home>",
    "end": "<end>",
    "pgup": "<page_up>",
    "pgdn": "<page_down>",
    "pageup": "<page_up>",
    "pagedown": "<page_down>",
    "up": "<up>",
    "down": "<down>",
    "left": "<left>",
    "right": "<right>",
    "print": "<print_screen>",
    "pause": "<pause>",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "semicolon": ";",
    "minus": "-",
    "equal": "=",
}

# 反向映射，用于把 pynput 字符串显示回 Qt 的 QKeySequenceEdit
_REVERSE = {v: k for k, v in _SPECIAL.items()}
# 修饰键必须先映射，否则会被下面的 <xxx> 兜底分支大写成 CTRL
_REVERSE.update({"<ctrl>": "Ctrl", "<alt>": "Alt", "<shift>": "Shift", "<cmd>": "Meta"})


def normalize(combo: str) -> str:
    """把松散写法（ctrl+alt+q）归一成 pynput 规范格式（<ctrl>+<alt>+q）。

    这样即使用户手改过配置文件、或旧版本留下了不带尖括号的值，热键依然能注册成功。
    """
    if not combo:
        return ""
    parts: list[str] = []
    for tok in str(combo).split("+"):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith("<") and tok.endswith(">"):
            parts.append(tok.lower())
            continue
        low = tok.lower()
        if low in _MOD_MAP:
            parts.append(_MOD_MAP[low])
        elif low in _SPECIAL:
            parts.append(_SPECIAL[low])
        elif len(tok) == 1:
            parts.append(tok.lower())
        else:
            parts.append(f"<{low}>")
    # 安全校验：必须同时有修饰键和普通键。
    # 只有修饰键（如 <ctrl>）会在每一次按 Ctrl 时误触发；
    # 裸普通键（如 q）会劫持正常打字。两种情况一律判为无效。
    has_modifier = any(t in _MOD_MAP.values() for t in parts)
    has_normal = any(t not in _MOD_MAP.values() for t in parts)
    if not (has_modifier and has_normal):
        return ""
    return "+".join(parts)


def _token_to_pynput(token: str) -> str | None:
    t = token.strip().lower()
    if not t:
        return None
    if t in _MOD_MAP:
        return _MOD_MAP[t]
    if t in _SPECIAL:
        return _SPECIAL[t]
    if t.startswith("f") and t[1:].isdigit() and 1 <= int(t[1:]) <= 24:
        return f"<{t}>"
    if len(t) == 1 and (t.isalnum() or not t.isascii()):
        return t
    # 其余单字符（如 ; , . / - =）
    if len(t) == 1:
        return t
    return None


def qt_to_pynput(sequence: str) -> str:
    """把 QKeySequence 文本（Ctrl+Alt+Q）转成 pynput 格式（<ctrl>+<alt>+q）。

    无法识别的组合返回空串，由调用方提示用户。
    """
    if not sequence:
        return ""
    tokens = [t for t in sequence.replace(" ", "").split("+") if t]
    out: list[str] = []
    for tok in tokens:
        conv = _token_to_pynput(tok)
        if conv is None:
            log.warning("无法识别的热键片段：%s（来自 %s）", tok, sequence)
            return ""
        out.append(conv)
    # 至少需要一个非修饰键，否则会被误触发
    if len(out) < 2 or all(t.startswith("<") and t in _MOD_MAP.values() for t in out):
        return ""
    return "+".join(out)


def pynput_to_qt(combo: str) -> str:
    """反向转换，用于把配置显示进设置界面。"""
    if not combo:
        return ""
    parts = []
    for tok in combo.split("+"):
        tok = tok.strip()
        if not tok:
            continue
        if tok in _REVERSE:
            parts.append(_REVERSE[tok])
        elif tok.startswith("<") and tok.endswith(">"):
            parts.append(tok[1:-1].upper())
        else:
            parts.append(tok.upper())
    return "+".join(parts)


def sequence_is_valid(sequence: str) -> bool:
    return bool(qt_to_pynput(sequence))


def display_text(combo: str) -> str:
    """给界面看的热键文案。"""
    return pynput_to_qt(normalize(combo)) or combo or "未设置"


class HotkeyManager(QObject):
    """热键管理器：配置变更后调用 start() 重建监听。"""

    triggered = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener = None
        self._hotkey = None
        self._combo = ""
        self._last_error = ""

    @property
    def combo(self) -> str:
        return self._combo

    @property
    def active(self) -> bool:
        return self._listener is not None and self._hotkey is not None

    def start(self, combo: str) -> bool:
        self.stop()
        combo = normalize(combo)
        if not combo:
            self.failed.emit(
                "热键无效：需要「修饰键（Ctrl/Alt/Shift）+ 普通键」的组合，例如 Ctrl+Alt+Q。"
            )
            return False
        try:
            from pynput import keyboard
        except Exception as e:  # noqa: BLE001
            msg = f"全局热键不可用（pynput 加载失败）：{e}"
            log.warning(msg)
            self.failed.emit(msg)
            return False

        def _on_activate() -> None:
            # 此回调运行在监听线程，只允许发信号
            try:
                self.triggered.emit()
            except RuntimeError:
                pass  # 对象已销毁

        try:
            hotkey = keyboard.HotKey(keyboard.HotKey.parse(combo), _on_activate)
        except Exception as e:  # noqa: BLE001
            msg = f"热键 {combo} 无法解析：{e}"
            log.warning(msg)
            self.failed.emit(msg)
            return False

        # 为什么不用 keyboard.GlobalHotKeys：
        # 实测 pynput 1.8.2 的 GlobalHotKeys 在 Windows 上 start() 返回正常、running=True，
        # 但按键时回调永远不触发（<f9> 这种单键也不触发）。改用官方文档推荐的
        # 「HotKey + Listener 手工桥接」后，<f9> 与 <ctrl>+<alt>+q 均能正常触发。
        holder: list = []

        def _on_press(key) -> None:
            try:
                hotkey.press(holder[0].canonical(key))
            except Exception:  # noqa: BLE001
                pass

        def _on_release(key) -> None:
            try:
                hotkey.release(holder[0].canonical(key))
            except Exception:  # noqa: BLE001
                pass

        try:
            listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
            holder.append(listener)
            listener.daemon = True
            listener.start()
            listener.wait()  # 等键盘钩子就绪，避免启动瞬间漏掉按键
        except Exception as e:  # noqa: BLE001
            msg = f"热键 {combo} 注册失败：{e}（可能被其他软件占用，换一个组合试试）"
            log.warning(msg)
            self.failed.emit(msg)
            return False

        self._listener = listener
        self._hotkey = hotkey
        self._combo = combo
        log.info("全局热键已注册：%s", combo)
        return True

    def stop(self) -> None:
        if self._hotkey is not None:
            try:
                self._hotkey.reset()
            except Exception:  # noqa: BLE001
                pass
            self._hotkey = None
        if self._listener is not None:
            try:
                self._listener.stop()
                self._listener.join(timeout=1.0)
            except Exception as e:  # noqa: BLE001
                log.debug("停止热键监听失败: %s", e)
            self._listener = None
        self._combo = ""

    def restart(self, combo: str) -> bool:
        return self.start(combo)
