# 用真实 windows 平台渲染界面，检查字体与观感。仅用于验证。
import os, sys, tempfile, time
from pathlib import Path
ROOT = Path(r"E:/鸡哥解题"); sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="jige-render-"))
os.environ["JIGE_DATA_DIR"] = str(TMP)
OUT = ROOT / "_verify"; OUT.mkdir(exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import QRect, QPoint
from app import capture as cap, config as cfgmod
from app.config import ConfigManager
from app.store import Store
from app.ui import theme
from app.ui.float_window import FloatWindow
from app.ui.overlay import CaptureOverlay
from app.ui.settings_dialog import SettingsDialog
from app.ui.history_dialog import HistoryDialog

app = QApplication([])
app.setFont(theme.app_font(12)); app.setStyleSheet(theme.STYLESHEET)
print("平台:", app.platformName(), "| 字体数:", len(__import__("PySide6.QtGui", fromlist=["QFontDatabase"]).QFontDatabase.families()))
print("app_font ->", theme.app_font(12).family())

cfgmod.ensure_dirs()
config = ConfigManager()
config.config.engine.provider = "ollama"
store = Store()

SAMPLE = ("**考查知识点**：一元二次方程求解。\n\n"
          "### 解题步骤\n"
          "1. 由 $ax^2+bx+c=0$ 得判别式 $\\Delta = b^2-4ac = 25$；\n"
          "2. 代入求根公式 $x=\\frac{-b\\pm\\sqrt{\\Delta}}{2a}$，得到 $x_1=1$，$x_2=-6$。\n\n"
          "**答案：** $x_1 = 1,\\ x_2 = -6$")
img = QImage(300, 90, QImage.Format_RGB32); img.fill(QColor("#E8EEF8"))
png = cap.to_png_bytes(img)
rel = store.save_shot(png, "png")
from app.ui import formatting
store.add_record(source="image", question="求解 x^2+5x-6=0", answer=formatting.to_plain(SAMPLE),
                 provider="ollama", model="qwen2.5vl:7b", image_path=rel, elapsed_ms=4200,
                 style="detailed")
store.add_record(source="text", question="求 lim(x->0) sin(x)/x", answer="答案：1",
                 provider="ollama", model="qwen2.5vl:7b", elapsed_ms=1800, style="brief")

w = FloatWindow(config, store)
w.show()
for _ in range(30): app.processEvents(); time.sleep(0.02)
w._accumulated = SAMPLE
w.answer_view.document().setMarkdown(formatting.to_markdown(SAMPLE))
w.answer_meta.setText("ollama · qwen2.5vl:7b · 4.2s")
w._set_status("就绪 · 按 Ctrl+Alt+Q 即可截图解题", theme.SUCCESS)
w.submit_image(img, png, note="求解 x^2+5x-6=0") if False else None
w._show_preview(img, rel)
for _ in range(20): app.processEvents(); time.sleep(0.02)
w.grab().save(str(OUT / "R1_float_text.png"))
w.tab_group.button(1).setChecked(True); w._on_tab_changed(1)
app.processEvents(); time.sleep(0.05)
w.grab().save(str(OUT / "R2_float_shot.png"))
w.set_collapsed(True)
for _ in range(10): app.processEvents(); time.sleep(0.02)
# 收起态整个窗口都是透明的，直接存 PNG 会看不出边界，垫一层灰底
from PySide6.QtGui import QPainter as _QPainter, QPixmap  # noqa: E402
_canvas = QPixmap(w.size())
_canvas.fill(QColor("#E9EDF5"))
_p = _QPainter(_canvas)
_p.drawPixmap(0, 0, w.grab())
_p.end()
_canvas.save(str(OUT / "R3_float_collapsed.png"))
w.set_collapsed(False)

d = SettingsDialog(config, store); d.show()
for _ in range(20): app.processEvents(); time.sleep(0.02)
d.grab().save(str(OUT / "R4_settings_engine.png"))
d.tabs.setCurrentIndex(1); app.processEvents(); time.sleep(0.05); d.grab().save(str(OUT / "R5_settings_hotkey.png"))
d.tabs.setCurrentIndex(2); app.processEvents(); time.sleep(0.05); d.grab().save(str(OUT / "R6_settings_data.png"))
d.close()

h = HistoryDialog(store); h.show()
for _ in range(20): app.processEvents(); time.sleep(0.02)
h.grab().save(str(OUT / "R7_history.png")); h.close()

screen = QImage(1440, 900, QImage.Format_RGB32); screen.fill(QColor("#CBD5E4"))
ov = CaptureOverlay(screen, 1.0, QRect(0,0,1440,900), mode="region")
ov.show(); ov._origin = QPoint(200, 160); ov._current = QPoint(900, 520); ov._dragging = True; ov.update()
for _ in range(20): app.processEvents(); time.sleep(0.02)
ov.grab().save(str(OUT / "R8_overlay.png"))
ov.close()

# ---- R9 果冻悬浮球的各状态（静息 / 悬停·挤压 / 悬停·弹起 / 右键抖动 / 左键按住 / 拖动捏扁）----
from PySide6.QtWidgets import QWidget  # noqa: E402
from PySide6.QtGui import QPainter, QPen  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from app.ui.jelly import PADDING as _PADDING, JellyBubble  # noqa: E402
from app.ui.float_window import COLLAPSED_SIZE as _COLLAPSED  # noqa: E402

CELL, PAD, CAP_H = _COLLAPSED.width(), 20, 24

# (名称, scale, glow, squash)：squash 正值 = 压扁（横向鼓、纵向扁），负值 = 纵向拉长
STATES = [
    ("静息", 1.00, 0.00, 0.00),
    ("悬停·挤压", 1.12, 1.00, 1.15),
    ("悬停·弹起", 1.12, 1.00, -0.38),
    ("右键·抖动", 1.12, 1.00, -0.55),
    ("左键·按住", 1.00, 0.50, 1.00),
    ("拖动·捏扁", 1.00, 0.35, 0.35),
]


class _Stage(QWidget):
    """给每个球垫一圈「静息直径」的虚线参考圆。

    光晕是一大片柔和的圆形光斑，光看球体很难判断到底压扁了没有 ——
    有了这圈参照，任何偏离圆形的状态都一眼可见（横向鼓出 / 纵向拉长）。
    """

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#E9EDF5"))
        p.setRenderHint(QPainter.Antialiasing, True)
        r = CELL / 2.0 - _PADDING
        p.setPen(QPen(QColor(96, 118, 156, 150), 1, Qt.DashLine))
        for i in range(len(STATES)):
            cx, cy = PAD + i * CELL + CELL / 2.0, PAD + CELL / 2.0
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QColor("#4A5B78"))
        p.setFont(theme.app_font(10))
        for i, (name, *_rest) in enumerate(STATES):
            p.drawText(QRectF(PAD + i * CELL, PAD + CELL + 3, CELL, CAP_H),
                       Qt.AlignHCenter | Qt.AlignTop, name)
        p.end()


stage = _Stage()
stage.setFixedSize(CELL * len(STATES) + PAD * 2, CELL + PAD * 2 + CAP_H)
balls = []
for i, (_name, s, g, q) in enumerate(STATES):
    b = JellyBubble(stage)
    b.setGeometry(PAD + i * CELL, PAD, CELL, CELL)
    b.show()
    balls.append(b)
stage.show()
for _ in range(10):
    app.processEvents(); time.sleep(0.02)
# 定格必须放在 stage.show() 之后：showEvent 会重新启动「呼吸」动画，
# 先设值再显示的话抓到的是别的帧，不是我们指定的状态。
for b, (_name, s, g, q) in zip(balls, STATES):
    b.stop_animations()
    b._scale, b._glow, b._squash, b._pulse = s, g, q, 1.0
    b.update()
for _ in range(8):
    app.processEvents(); time.sleep(0.02)
stage.grab().save(str(OUT / "R9_jelly_states.png"))
for b in balls:
    b.stop_animations()
stage.close()

w.close(); store.close()
print("渲染完成 ->", OUT)
