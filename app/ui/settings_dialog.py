"""设置对话框：引擎、热键与截屏、数据管理三页。"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config as cfgmod
from app import logger as logmod
from app.config import ANSWER_STYLE_LABELS, ANSWER_STYLES, KEEP_ALIVE_CHOICES, ConfigManager
from app.engine.base import detect_models, is_missing_model_error, parse_extra_body
from app.engine.presets import PRESETS, preset_labels
from app.engine.service import WIRE_CHOICES
from app.hotkey import display_text, qt_to_pynput, sequence_is_valid
from app.logger import get
from app.store import Store
from app.ui import theme

log = get("settings")
from app.ui.worker import TestWorker


class SettingsDialog(QDialog):
    applied = Signal()

    def __init__(self, config: ConfigManager, store: Store, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        self._test_worker: TestWorker | None = None

        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(theme.STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_engine_tab(), "引擎")
        self.tabs.addTab(self._build_hotkey_tab(), "热键与截屏")
        self.tabs.addTab(self._build_data_tab(), "数据与清理")
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()

    # ============================================================ 引擎页

    def _build_engine_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(8)

        self.provider_box = QComboBox(page)
        for key, label in preset_labels():
            self.provider_box.addItem(label, key)
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("服务商", self.provider_box)

        self.base_url_edit = QLineEdit(page)
        self.base_url_edit.setPlaceholderText("例如 http://127.0.0.1:11434/v1")
        form.addRow("API 地址", self.base_url_edit)

        key_row = QWidget(page)
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(6)
        self.api_key_edit = QLineEdit(key_row)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("本机 Ollama 可留空")
        key_layout.addWidget(self.api_key_edit, 1)
        self.show_key_check = QCheckBox("显示", key_row)
        self.show_key_check.toggled.connect(
            lambda on: self.api_key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        key_layout.addWidget(self.show_key_check)
        form.addRow("API Key", key_row)

        model_row = QWidget(page)
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(6)
        self.model_edit = QLineEdit(model_row)
        self.model_edit.setPlaceholderText("例如 qwen2.5vl:7b")
        model_layout.addWidget(self.model_edit, 1)
        self.detect_btn = QPushButton("检测本机模型", model_row)
        self.detect_btn.setToolTip(
            "让服务端把已安装的模型列出来，点选即可填入；\n"
            "配上「测试连接」可以避免「模型名写错/没装」这类最常见的失败。"
        )
        self.detect_btn.clicked.connect(self._on_detect_models)
        model_layout.addWidget(self.detect_btn)
        form.addRow("模型名", model_row)

        self.wire_box = QComboBox(page)
        for key, label in WIRE_CHOICES:
            self.wire_box.addItem(label, key)
        form.addRow("接口协议", self.wire_box)

        self.extra_body_edit = QLineEdit(page)
        self.extra_body_edit.setPlaceholderText('额外请求参数，JSON 对象；留空表示不加。例：{"think": false}')
        self.extra_body_edit.setToolTip(
            "用于适配各家私有开关：Ollama 的 think、通义的 enable_thinking、智谱的 thinking 等。\n"
            "本机 Ollama 默认已填 {\"think\": false}：带思考模式的模型如果不关掉，\n"
            "输出预算会被内部推理耗尽，表现为答案空白或被截断。"
        )
        form.addRow("额外请求参数", self.extra_body_edit)

        num_row = QWidget(page)
        num_layout = QHBoxLayout(num_row)
        num_layout.setContentsMargins(0, 0, 0, 0)
        num_layout.setSpacing(10)
        self.temp_spin = QDoubleSpinBox(num_row)
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(2)
        num_layout.addWidget(QLabel("温度", num_row))
        num_layout.addWidget(self.temp_spin)
        num_layout.addSpacing(8)
        self.max_tokens_spin = QSpinBox(num_row)
        self.max_tokens_spin.setRange(0, 32768)
        self.max_tokens_spin.setSingleStep(256)
        self.max_tokens_spin.setToolTip(
            "0 表示不限制。\n"
            "输出长度直接决定等待时间：「只看答案」风格会自动封顶到 512，不会超过这里设的值。"
        )
        num_layout.addWidget(QLabel("最大输出", num_row))
        num_layout.addWidget(self.max_tokens_spin)
        num_layout.addSpacing(8)
        self.timeout_spin = QSpinBox(num_row)
        self.timeout_spin.setRange(10, 900)
        self.timeout_spin.setSuffix(" 秒")
        num_layout.addWidget(QLabel("超时", num_row))
        num_layout.addWidget(self.timeout_spin)
        num_layout.addStretch(1)
        form.addRow("生成参数", num_row)

        self.style_box = QComboBox(page)
        for key in ANSWER_STYLES:
            self.style_box.addItem(ANSWER_STYLE_LABELS[key], key)
        self.style_box.setToolTip(
            "只看答案：只输出最终结果，回答很短，所以明显更快（输出长度是主要耗时来源）。\n"
            "详细题解：给出知识点和完整解题步骤。\n"
            "悬浮窗上也有同一个开关，可以随时切。"
        )
        form.addRow("解答风格", self.style_box)
        self.style_box.currentIndexChanged.connect(self._update_prompt_note)

        self.keep_alive_box = QComboBox(page)
        for value, label in KEEP_ALIVE_CHOICES:
            self.keep_alive_box.addItem(label, value)
        self.keep_alive_box.setToolTip(
            "仅对本机 Ollama 的「原生协议」生效，决定模型在显存里留多久。\n"
            "Ollama 自带默认是 5 分钟，超时会把模型卸载，下次提问要重新加载\n"
            "—— 实测 9B 模型冷启动约 85 秒，热态只要 5-15 秒，差距远大于任何参数调优。\n"
            "显存紧张就调小；追求响应速度就调大或设成常驻。\n"
            "注意：若「接口协议」选了 OpenAI 兼容，这里不生效；\n"
            "那种情况下请设系统环境变量 OLLAMA_KEEP_ALIVE=30m。"
        )
        form.addRow("模型驻留", self.keep_alive_box)
        layout.addLayout(form)

        self.preset_hint = QLabel(page)
        self.preset_hint.setObjectName("hintLabel")
        self.preset_hint.setWordWrap(True)
        layout.addWidget(self.preset_hint)

        prompt_group = QGroupBox("系统提示词（留空 = 按「解答风格」自动生成）", page)
        prompt_layout = QVBoxLayout(prompt_group)
        self.prompt_edit = QPlainTextEdit(prompt_group)
        self.prompt_edit.setMinimumHeight(96)
        self.prompt_edit.setPlaceholderText(
            "留空即可：程序会按上面选的「解答风格」自动套用内置提示词。\n"
            "一旦在这里填了内容，就完全覆盖风格开关（切「只看答案 / 详细题解」不再生效）。"
        )
        self.prompt_edit.textChanged.connect(self._update_prompt_note)
        prompt_layout.addWidget(self.prompt_edit)
        self.prompt_note = QLabel("", prompt_group)
        self.prompt_note.setObjectName("hintLabel")
        self.prompt_note.setWordWrap(True)
        prompt_layout.addWidget(self.prompt_note)
        layout.addWidget(prompt_group)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接", page)
        self.test_btn.clicked.connect(self._on_test)
        test_row.addWidget(self.test_btn)
        self.test_result = QLabel("", page)
        self.test_result.setObjectName("hintLabel")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_result, 1)
        layout.addLayout(test_row)
        layout.addStretch(1)
        return page

    # ============================================================ 热键页

    def _build_hotkey_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        hk_group = QGroupBox("全局热键（任何程序里都能触发截图）", page)
        hk_layout = QFormLayout(hk_group)
        hk_layout.setSpacing(8)

        self.hotkey_enabled = QCheckBox("启用全局热键", hk_group)
        hk_layout.addRow("", self.hotkey_enabled)

        self.hotkey_edit = QKeySequenceEdit(hk_group)
        self.hotkey_edit.setMaximumSequenceLength(1)
        hk_layout.addRow("截图热键", self.hotkey_edit)

        hk_tip = QLabel(
            "点击输入框后直接按组合键即可录入。\n"
            "建议 Ctrl+Alt+Q 之类不易冲突的组合；只按修饰键（如 Ctrl+Alt）无效。",
            hk_group,
        )
        hk_tip.setObjectName("hintLabel")
        hk_tip.setWordWrap(True)
        hk_layout.addRow("", hk_tip)
        layout.addWidget(hk_group)

        cap_group = QGroupBox("截屏行为", page)
        cap_layout = QFormLayout(cap_group)
        cap_layout.setSpacing(8)
        self.capture_mode_box = QComboBox(cap_group)
        self.capture_mode_box.addItem("鼠标框选题目区域（推荐）", "region")
        self.capture_mode_box.addItem("直接整屏截图", "fullscreen")
        cap_layout.addRow("默认方式", self.capture_mode_box)

        self.shot_width_spin = QSpinBox(cap_group)
        self.shot_width_spin.setRange(600, 4000)
        self.shot_width_spin.setSingleStep(100)
        self.shot_width_spin.setSuffix(" px")
        self.shot_width_spin.setToolTip(
            "截图送模型前的压缩宽度，直接影响截屏解题的速度：\n"
            "图片占用的 token 数与像素面积成正比，1600px 宽大约是 1024px 宽的 2.4 倍。\n"
            "题目字号小、要看清公式就调大；只求快、只要能认出大意就调小。\n"
            "1024 最快 / 1600 均衡（默认）/ 2000 以上更清晰但明显更慢。"
        )
        cap_layout.addRow("送模型前压缩宽度", self.shot_width_spin)

        self.jpeg_quality_spin = QSpinBox(cap_group)
        self.jpeg_quality_spin.setRange(40, 95)
        cap_layout.addRow("压缩画质", self.jpeg_quality_spin)
        layout.addWidget(cap_group)

        ui_group = QGroupBox("窗口", page)
        ui_layout = QFormLayout(ui_group)
        ui_layout.setSpacing(8)
        self.opacity_spin = QDoubleSpinBox(ui_group)
        self.opacity_spin.setRange(0.4, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        ui_layout.addRow("悬浮窗不透明度", self.opacity_spin)
        self.font_spin = QSpinBox(ui_group)
        self.font_spin.setRange(10, 20)
        ui_layout.addRow("字号", self.font_spin)
        layout.addWidget(ui_group)
        layout.addStretch(1)
        return page

    # ============================================================ 数据页

    def _build_data_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        path_group = QGroupBox("数据目录（所有记录与截图都在这里）", page)
        path_layout = QVBoxLayout(path_group)
        self.data_path_edit = QLineEdit(path_group)
        self.data_path_edit.setReadOnly(True)
        path_layout.addWidget(self.data_path_edit)

        row = QHBoxLayout()
        open_btn = QPushButton("打开目录", path_group)
        open_btn.clicked.connect(self._open_data_dir)
        row.addWidget(open_btn)
        refresh_btn = QPushButton("刷新统计", path_group)
        refresh_btn.clicked.connect(self._refresh_stats)
        row.addWidget(refresh_btn)
        row.addStretch(1)
        path_layout.addLayout(row)

        self.stats_label = QLabel("", path_group)
        self.stats_label.setObjectName("hintLabel")
        self.stats_label.setWordWrap(True)
        path_layout.addWidget(self.stats_label)

        tip = QLabel(
            "想彻底清理磁盘：先在这里清空，再删除上面这个目录即可，不会留下任何残留文件。",
            path_group,
        )
        tip.setObjectName("hintLabel")
        tip.setWordWrap(True)
        path_layout.addWidget(tip)
        layout.addWidget(path_group)

        keep_group = QGroupBox("保留策略", page)
        keep_layout = QFormLayout(keep_group)
        keep_layout.setSpacing(8)
        self.auto_trim_check = QCheckBox("超出上限时自动清理最旧记录", keep_group)
        keep_layout.addRow("", self.auto_trim_check)
        self.history_limit_spin = QSpinBox(keep_group)
        self.history_limit_spin.setRange(20, 20000)
        self.history_limit_spin.setSingleStep(50)
        self.history_limit_spin.setSuffix(" 条")
        keep_layout.addRow("历史保留上限", self.history_limit_spin)
        self.drop_orphan_check = QCheckBox("启动时自动清理孤儿截图", keep_group)
        keep_layout.addRow("", self.drop_orphan_check)
        layout.addWidget(keep_group)

        clean_group = QGroupBox("清理操作", page)
        clean_layout = QHBoxLayout(clean_group)
        self.clean_orphan_btn = QPushButton("清理孤儿文件", clean_group)
        self.clean_orphan_btn.setToolTip("删除磁盘上存在但数据库没有记录的截图")
        self.clean_orphan_btn.clicked.connect(self._on_clean_orphan)
        clean_layout.addWidget(self.clean_orphan_btn)

        self.clean_logs_btn = QPushButton("清理旧日志", clean_group)
        self.clean_logs_btn.clicked.connect(self._on_clean_logs)
        clean_layout.addWidget(self.clean_logs_btn)

        self.clean_all_btn = QPushButton("清空全部历史与截图", clean_group)
        self.clean_all_btn.setObjectName("danger")
        self.clean_all_btn.clicked.connect(self._on_clean_all)
        clean_layout.addWidget(self.clean_all_btn)
        clean_layout.addStretch(1)
        layout.addWidget(clean_group)
        layout.addStretch(1)
        return page

    # ============================================================ 载入 / 保存

    def _load(self) -> None:
        cfg = self.config.config

        idx = self.provider_box.findData(cfg.engine.provider)
        self.provider_box.blockSignals(True)
        self.provider_box.setCurrentIndex(max(0, idx))
        self.provider_box.blockSignals(False)
        self.base_url_edit.setText(cfg.engine.base_url)
        self.api_key_edit.setText(cfg.engine.api_key)
        self.model_edit.setText(cfg.engine.model)
        self.extra_body_edit.setText(cfg.engine.extra_body)
        wire_idx = self.wire_box.findData(cfg.engine.wire_api)
        self.wire_box.setCurrentIndex(max(0, wire_idx))
        self.temp_spin.setValue(float(cfg.engine.temperature))
        self.max_tokens_spin.setValue(int(cfg.engine.max_tokens))
        self.timeout_spin.setValue(int(cfg.engine.timeout))
        style_idx = self.style_box.findData(cfg.engine.style)
        self.style_box.blockSignals(True)
        self.style_box.setCurrentIndex(max(0, style_idx))
        self.style_box.blockSignals(False)
        alive_value = cfg.engine.resolved_keep_alive()
        alive_idx = self.keep_alive_box.findData(alive_value)
        if alive_idx < 0:
            # 用户手改过 config.json 写了非预设值，这里补一个条目，避免把配置静默改掉
            if alive_value:
                self.keep_alive_box.addItem(f"自定义：{alive_value}", alive_value)
                alive_idx = self.keep_alive_box.count() - 1
        self.keep_alive_box.setCurrentIndex(max(0, alive_idx))
        self.prompt_edit.setPlainText(cfg.engine.system_prompt)
        self._update_prompt_note()
        self._update_preset_hint()

        self.hotkey_enabled.setChecked(bool(cfg.hotkey.enabled))
        self.hotkey_edit.setKeySequence(QKeySequence(display_text(cfg.hotkey.capture)))
        mode_idx = self.capture_mode_box.findData(cfg.capture.mode)
        self.capture_mode_box.setCurrentIndex(max(0, mode_idx))
        self.shot_width_spin.setValue(int(cfg.capture.shot_max_width))
        self.jpeg_quality_spin.setValue(int(cfg.capture.jpeg_quality))

        self.opacity_spin.setValue(float(cfg.ui.opacity))
        self.font_spin.setValue(int(cfg.ui.font_size))

        self.data_path_edit.setText(str(cfgmod.data_dir()))
        self.auto_trim_check.setChecked(bool(cfg.storage.auto_trim))
        self.history_limit_spin.setValue(int(cfg.storage.history_limit))
        self.drop_orphan_check.setChecked(bool(cfg.storage.drop_orphan_shots))
        self._refresh_stats()

    def _update_prompt_note(self) -> None:
        """告诉用户「现在真正生效的提示词是哪一份」，避免风格开关看起来没反应。"""
        if self.prompt_edit.toPlainText().strip():
            self.prompt_note.setText(
                "当前生效：上面这份自定义提示词。「只看答案 / 详细题解」开关对它不起作用"
                "（清空本框即可恢复由风格决定）。"
            )
        else:
            key = self.style_box.currentData()
            label = ANSWER_STYLE_LABELS.get(key, key)
            self.prompt_note.setText(f"当前生效：内置的「{label}」提示词（本框留空）。")

    def _update_preset_hint(self) -> None:
        key = self.provider_box.currentData()
        preset = PRESETS.get(key, {})
        vision = "支持图片（可截屏解题）" if preset.get("vision", True) else "仅文本，不支持截屏解题"
        self.preset_hint.setText(f"说明：{preset.get('hint', '')}\n能力：{vision}")

    def _on_provider_changed(self) -> None:
        key = self.provider_box.currentData()
        preset = PRESETS.get(key)
        if not preset:
            return
        self.base_url_edit.setText(preset["base_url"])
        self.model_edit.setText(preset["model"])
        self.extra_body_edit.setText(preset.get("extra_body", ""))
        wire_idx = self.wire_box.findData(preset["wire_api"])
        if wire_idx >= 0:
            self.wire_box.setCurrentIndex(wire_idx)
        self._update_preset_hint()

    def _on_save(self) -> None:
        cfg = self.config.config
        sequence = self.hotkey_edit.keySequence().toString()
        combo = qt_to_pynput(sequence)
        if self.hotkey_enabled.isChecked() and not sequence_is_valid(sequence):
            QMessageBox.warning(
                self,
                "热键无效",
                f"「{sequence or '空'}」不是有效的组合键。\n请至少包含一个修饰键（Ctrl / Alt / Shift）+ 一个普通键。",
            )
            return

        cfg.engine.provider = self.provider_box.currentData()
        cfg.engine.base_url = self.base_url_edit.text().strip()
        cfg.engine.api_key = self.api_key_edit.text().strip()
        cfg.engine.model = self.model_edit.text().strip()
        extra_body = self.extra_body_edit.text().strip()
        try:
            parse_extra_body(extra_body)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "额外请求参数有误", str(e))
            return
        cfg.engine.extra_body = extra_body
        cfg.engine.wire_api = self.wire_box.currentData()
        cfg.engine.temperature = float(self.temp_spin.value())
        cfg.engine.max_tokens = int(self.max_tokens_spin.value())
        cfg.engine.timeout = int(self.timeout_spin.value())
        style = self.style_box.currentData()
        if style in ANSWER_STYLES:
            cfg.engine.answer_style = style
        keep = (self.keep_alive_box.currentData() or "").strip()
        if keep:
            cfg.engine.keep_alive = keep
        cfg.engine.system_prompt = self.prompt_edit.toPlainText().strip()

        if combo:
            cfg.hotkey.capture = combo
        cfg.hotkey.enabled = self.hotkey_enabled.isChecked()
        cfg.capture.mode = self.capture_mode_box.currentData()
        cfg.capture.shot_max_width = int(self.shot_width_spin.value())
        cfg.capture.jpeg_quality = int(self.jpeg_quality_spin.value())
        cfg.ui.opacity = float(self.opacity_spin.value())
        cfg.ui.font_size = int(self.font_spin.value())
        cfg.storage.auto_trim = self.auto_trim_check.isChecked()
        cfg.storage.history_limit = int(self.history_limit_spin.value())
        cfg.storage.drop_orphan_shots = self.drop_orphan_check.isChecked()

        self.store.drop_orphan = cfg.storage.drop_orphan_shots
        self.config.save()
        self.applied.emit()
        self.accept()

    # ============================================================ 测试 / 清理

    def _engine_snapshot(self):
        """按界面当前内容拼一份引擎配置（不落盘），供「检测模型」「测试连接」使用。"""
        cfg = self.config.config.engine
        snap = type(cfg)(**{**cfg.__dict__})
        snap.provider = self.provider_box.currentData()
        snap.base_url = self.base_url_edit.text().strip()
        snap.api_key = self.api_key_edit.text().strip() or cfgmod.ConfigManager.effective_api_key("")
        snap.model = self.model_edit.text().strip()
        snap.wire_api = self.wire_box.currentData()
        snap.extra_body = self.extra_body_edit.text().strip()
        snap.timeout = max(20, int(self.timeout_spin.value()))
        snap.answer_style = self.style_box.currentData() or snap.answer_style
        snap.keep_alive = (self.keep_alive_box.currentData() or "").strip() or snap.keep_alive
        return snap

    def _on_detect_models(self) -> None:
        """列出服务端已安装的模型，点选直接填入「模型名」。

        这一步能挡掉最常见的失败：模型名写错、或本地根本没装那个模型
        （预设给的是通用推荐值，不代表你机器上已经拉下来了）。
        """
        snap = self._engine_snapshot()
        self.detect_btn.setEnabled(False)
        self.detect_btn.setText("检测中…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            names = detect_models(snap)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "检测失败", str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.detect_btn.setText("检测本机模型")
            self.detect_btn.setEnabled(True)

        if not names:
            QMessageBox.information(
                self, "没有可用模型",
                "服务端没有返回任何模型。\n若用的是本机 Ollama，请先执行 `ollama pull <模型名>` 下载一个。",
            )
            return

        current = self.model_edit.text().strip()
        idx = names.index(current) if current in names else 0
        picked, ok = QInputDialog.getItem(self, "选择模型", "服务端已安装的模型：", names, idx, False)
        if ok and picked:
            self.model_edit.setText(picked)
            log.info("已选择模型：%s", picked)

    def _on_test(self) -> None:
        snapshot = self._engine_snapshot()

        self.test_btn.setEnabled(False)
        self.test_result.setText("正在测试…")
        self.test_result.setStyleSheet(f"color:{theme.TEXT_MUTED};")
        self._test_worker = TestWorker(snapshot, self)
        self._test_worker.finished_test.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_done(self, ok: bool, message: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_result.setText(message)
        self.test_result.setStyleSheet(f"color:{theme.SUCCESS if ok else theme.DANGER};")
        self._test_worker = None
        # 「模型没装」是首次运行最常见的失败，直接把修复动作摆到用户面前，
        # 而不是让他自己在设置页里找到那个按钮。
        if not ok and is_missing_model_error(message):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("模型不存在")
            box.setText(message)
            fix_btn = box.addButton("检测本机模型", QMessageBox.AcceptRole)
            box.addButton("知道了", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is fix_btn:
                self._on_detect_models()

    def _refresh_stats(self) -> None:
        stats = self.store.stats()
        size_mb = stats["bytes"] / 1024 / 1024
        total_mb = self.store.data_dir_size() / 1024 / 1024
        self.stats_label.setText(
            f"历史记录 {stats['records']} 条 ｜ 截图 {stats['files']} 张（{size_mb:.2f} MB）\n"
            f"数据目录总占用 {total_mb:.2f} MB"
        )

    def _open_data_dir(self) -> None:
        root = cfgmod.data_dir()
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def _on_clean_orphan(self) -> None:
        res = self.store.reconcile(drop_orphans=True)
        self._refresh_stats()
        QMessageBox.information(
            self,
            "清理完成",
            f"删除孤儿截图 {res['orphan_deleted']} 张，\n清理失效引用 {res['dangling_cleared']} 条。",
        )

    def _on_clean_logs(self) -> None:
        removed = logmod.cleanup_logs(0)
        QMessageBox.information(self, "清理完成", f"已删除 {removed} 个旧日志文件。")

    def _on_clean_all(self) -> None:
        stats = self.store.stats()
        confirm = QMessageBox.question(
            self,
            "确认清空",
            f"将删除全部 {stats['records']} 条历史记录和 {stats['files']} 张截图，且不可恢复。\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        res = self.store.clear_all()
        logmod.cleanup_logs(0)
        self._refresh_stats()
        QMessageBox.information(
            self, "已清空", f"删除记录 {res['records']} 条，截图 {res['files']} 张，日志已清理。"
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._test_worker is not None and self._test_worker.isRunning():
            self._test_worker.wait(1500)
        super().closeEvent(event)
