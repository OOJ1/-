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
w.grab().save(str(OUT / "R3_float_collapsed.png"))
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
ov.close(); w.close(); store.close()
print("渲染完成 ->", OUT)
