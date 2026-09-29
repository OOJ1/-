"""历史记录对话框：左侧列表 + 右侧原题/截图/答案详情，支持删除与清空。"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app import config as cfgmod
from app.config import ANSWER_STYLE_LABELS
from app.store import SOURCE_IMAGE, Store
from app.ui import formatting, theme


class HistoryDialog(QDialog):
    def __init__(self, store: Store, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._rows: list[dict] = []

        self.setWindowTitle("历史记录")
        self.setModal(False)
        self.resize(880, 560)
        self.setStyleSheet(theme.STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("搜索题干或答案关键字…")
        self.search_edit.returnPressed.connect(self.reload)
        top.addWidget(self.search_edit, 1)
        search_btn = QPushButton("搜索", self)
        search_btn.clicked.connect(self.reload)
        top.addWidget(search_btn)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.delete_btn = QPushButton("删除选中", self)
        self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        bottom.addWidget(self.delete_btn)

        clear_btn = QPushButton("清空全部", self)
        clear_btn.setObjectName("danger")
        clear_btn.clicked.connect(self._on_clear_all)
        bottom.addWidget(clear_btn)

        open_btn = QPushButton("打开数据目录", self)
        open_btn.clicked.connect(self._open_data_dir)
        bottom.addWidget(open_btn)

        bottom.addStretch(1)
        self.count_label = QLabel("", self)
        self.count_label.setObjectName("hintLabel")
        bottom.addWidget(self.count_label)

        close_btn = QPushButton("关闭", self)
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        self.reload()

    # ============================================================ 构建

    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["时间", "来源", "风格", "题目 / 答案摘要"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_row_changed)
        return self.table

    def _build_detail(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)

        self.meta_label = QLabel("选中左侧记录查看详情", page)
        self.meta_label.setObjectName("subLabel")
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)

        layout.addWidget(self._section_label("题目", page))
        self.question_view = QPlainTextEdit(page)
        self.question_view.setReadOnly(True)
        self.question_view.setMaximumHeight(96)
        layout.addWidget(self.question_view)

        layout.addWidget(self._section_label("题目截图", page))
        self.shot_label = QLabel(page)
        self.shot_label.setMinimumHeight(60)
        self.shot_label.setAlignment(Qt.AlignCenter)
        self.shot_label.setStyleSheet(
            f"border:1px dashed {theme.BORDER}; border-radius:8px; color:{theme.TEXT_MUTED};"
        )
        layout.addWidget(self.shot_label)

        layout.addWidget(self._section_label("解答", page))
        self.answer_view = QTextBrowser(page)
        self.answer_view.setOpenExternalLinks(True)
        layout.addWidget(self.answer_view, 1)
        return page

    def _section_label(self, text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setObjectName("titleLabel")
        return label

    # ============================================================ 数据

    def reload(self) -> None:
        keyword = self.search_edit.text().strip()
        self._rows = self.store.list_records(limit=1000, keyword=keyword)
        self.table.setRowCount(len(self._rows))
        for row, rec in enumerate(self._rows):
            created = str(rec["created_at"]).replace("T", " ")
            source = "截图" if rec["source"] == SOURCE_IMAGE else "文字"
            style = ANSWER_STYLE_LABELS.get(str(rec.get("style") or ""), "详细题解")
            summary = formatting.preview(rec["question"] or rec["answer"], 80)
            if rec["status"] != "ok":
                summary = "（未完成 / 出错）" + summary
            for col, value in enumerate((created, source, style, summary)):
                item = QTableWidgetItem(value)
                if col == 3:
                    item.setToolTip(rec["answer"][:300])
                self.table.setItem(row, col, item)
        self.count_label.setText(f"共 {len(self._rows)} 条")
        if self._rows:
            self.table.selectRow(0)
        else:
            self._clear_detail("没有匹配的记录")

    def _current_rows(self) -> list[dict]:
        indexes = sorted({idx.row() for idx in self.table.selectedIndexes()})
        return [self._rows[i] for i in indexes if 0 <= i < len(self._rows)]

    def _on_row_changed(self) -> None:
        selected = self._current_rows()
        if not selected:
            return
        rec = selected[0]
        created = str(rec["created_at"]).replace("T", " ")
        meta = [created, f"{rec['provider'] or '-'} / {rec['model'] or '-'}"]
        meta.append(ANSWER_STYLE_LABELS.get(str(rec.get("style") or ""), "详细题解"))
        if rec["elapsed_ms"]:
            meta.append(f"{rec['elapsed_ms'] / 1000:.1f}s")
        self.meta_label.setText(" ｜ ".join(meta))

        self.question_view.setPlainText(rec["question"] or "（无文字题干）")
        if rec["status"] != "ok" and rec["error"]:
            self.answer_view.setPlainText(f"[出错] {rec['error']}\n\n{rec['answer']}")
            self.answer_view.setStyleSheet(f"color:{theme.DANGER};")
        else:
            self.answer_view.document().setMarkdown(formatting.to_markdown(rec["answer"]))
            self.answer_view.setStyleSheet("")
        self._show_shot(rec.get("image_path"))

    def _show_shot(self, image_path: str | None) -> None:
        self.shot_label.setPixmap(QPixmap())
        if not image_path:
            self.shot_label.setText("（本题为文字输入，没有截图）")
            self.shot_label.setFixedHeight(60)
            return
        path = self.store.abs_shot_path(image_path)
        if path is None or not path.exists():
            self.shot_label.setText("（截图文件已被清理）")
            self.shot_label.setFixedHeight(60)
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            self.shot_label.setText("（图片无法读取）")
            self.shot_label.setFixedHeight(60)
            return
        target_w = 320
        scaled = pix.scaledToWidth(min(target_w, pix.width()), Qt.SmoothTransformation)
        self.shot_label.setPixmap(scaled)
        self.shot_label.setFixedHeight(min(scaled.height(), 220))

    def _clear_detail(self, text: str) -> None:
        self.meta_label.setText(text)
        self.question_view.setPlainText("")
        self.answer_view.setPlainText("")
        self.shot_label.setPixmap(QPixmap())
        self.shot_label.setText("")

    # ============================================================ 操作

    def _on_delete_selected(self) -> None:
        rows = self._current_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先选中要删除的记录。")
            return
        confirm = QMessageBox.question(
            self,
            "确认删除",
            f"将删除 {len(rows)} 条记录及其截图文件，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        removed = self.store.delete_records([r["id"] for r in rows])
        self.reload()
        self.meta_label.setText(f"已删除 {removed} 条记录。")

    def _on_clear_all(self) -> None:
        stats = self.store.stats()
        confirm = QMessageBox.question(
            self,
            "确认清空",
            f"将删除全部 {stats['records']} 条记录和 {stats['files']} 张截图，不可恢复。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        res = self.store.clear_all()
        self.reload()
        self.meta_label.setText(f"已清空：记录 {res['records']} 条，截图 {res['files']} 张。")

    def _open_data_dir(self) -> None:
        root = cfgmod.data_dir()
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))
