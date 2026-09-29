"""持久化层：SQLite 历史索引 + 截图目录，双向对账保证不留孤儿文件。

「无孤儿文件」的两条保证：
1. 写入：先落盘图片再写数据库记录，失败则回滚删除图片；
2. 对账 reconcile()：删除「磁盘有、数据库无」的图片；清理「数据库有、磁盘无」的空引用。
   启动时自动跑一次，设置页也可手动触发。
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from app import config as cfgmod
from app.logger import get

log = get("store")

SOURCE_TEXT = "text"
SOURCE_IMAGE = "image"
STATUS_OK = "ok"
STATUS_ERROR = "error"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    question    TEXT    NOT NULL DEFAULT '',
    image_path  TEXT,
    answer      TEXT    NOT NULL DEFAULT '',
    provider    TEXT    NOT NULL DEFAULT '',
    model       TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'ok',
    error       TEXT    NOT NULL DEFAULT '',
    elapsed_ms  INTEGER NOT NULL DEFAULT 0,
    style       TEXT    NOT NULL DEFAULT 'detailed'
);
CREATE INDEX IF NOT EXISTS idx_records_created ON records(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_records_image   ON records(image_path);
"""

# 老库升级：CREATE TABLE IF NOT EXISTS 不会给已有表补列，必须显式迁移。
_MIGRATIONS = (
    ("style", "ALTER TABLE records ADD COLUMN style TEXT NOT NULL DEFAULT 'detailed'"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(records)")}
    for column, ddl in _MIGRATIONS:
        if column not in existing:
            log.info("数据库迁移：新增列 %s", column)
            conn.execute(ddl)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


class Store:
    """线程安全的存储门面。UI 线程与工作线程共用。"""

    def __init__(
        self,
        db_file: Path | None = None,
        shots: Path | None = None,
        drop_orphan: bool = True,
    ) -> None:
        self.db_file = Path(db_file or cfgmod.db_path())
        self.shots = Path(shots or cfgmod.shots_dir())
        self.drop_orphan = drop_orphan
        self._lock = threading.RLock()
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.shots.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_file), check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        _migrate(self._conn)
        self._conn.commit()

    # ------------------------------------------------------------ 基础

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
                self._conn.close()
            except sqlite3.Error:
                pass

    def abs_shot_path(self, rel: str | None) -> Path | None:
        """把数据库里的相对路径还原为绝对路径，并做越界防护。"""
        if not rel:
            return None
        p = (self.db_file.parent / rel).resolve()
        try:
            p.relative_to(self.shots.resolve())
        except ValueError:
            log.warning("拒绝越界图片路径: %s", rel)
            return None
        return p

    # ------------------------------------------------------------ 图片

    def save_shot(self, data: bytes, ext: str = "png") -> str:
        """保存截图，返回相对数据根目录的路径（如 shots/20260928-xxxx.png）。"""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}-{uuid.uuid4().hex[:8]}.{ext}"
        dest = self.shots / name
        dest.write_bytes(data)
        return f"shots/{name}"

    def delete_shot(self, rel: str | None) -> bool:
        p = self.abs_shot_path(rel)
        if p and p.exists():
            try:
                p.unlink()
                return True
            except OSError as e:
                log.warning("删除截图失败 %s: %s", p, e)
        return False

    # ------------------------------------------------------------ 记录

    def add_record(
        self,
        *,
        source: str,
        question: str = "",
        image_path: str | None = None,
        answer: str = "",
        provider: str = "",
        model: str = "",
        status: str = STATUS_OK,
        error: str = "",
        elapsed_ms: int = 0,
        style: str = cfgmod.DEFAULT_ANSWER_STYLE,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO records (created_at, source, question, image_path, answer,"
                " provider, model, status, error, elapsed_ms, style)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    source,
                    question or "",
                    image_path,
                    answer or "",
                    provider or "",
                    model or "",
                    status,
                    error or "",
                    int(elapsed_ms),
                    style or cfgmod.DEFAULT_ANSWER_STYLE,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def update_record(self, record_id: int, **fields: Any) -> None:
        allowed = {"question", "answer", "status", "error", "elapsed_ms", "model", "provider", "image_path"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k}=?" for k in sets)
        with self._lock:
            self._conn.execute(
                f"UPDATE records SET {cols} WHERE id=?", (*sets.values(), record_id)
            )
            self._conn.commit()

    def get_record(self, record_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def list_records(self, limit: int = 200, offset: int = 0, keyword: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM records"
        args: list[Any] = []
        if keyword.strip():
            sql += " WHERE question LIKE ? OR answer LIKE ?"
            like = f"%{keyword.strip()}%"
            args += [like, like]
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args += [int(limit), int(offset)]
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [_row_to_dict(r) for r in rows]

    def count_records(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def delete_records(self, ids: Iterable[int]) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        removed = 0
        with self._lock:
            for rid in ids:
                row = self._conn.execute("SELECT image_path FROM records WHERE id=?", (rid,)).fetchone()
                if row is None:
                    continue
                self.delete_shot(row["image_path"])
                self._conn.execute("DELETE FROM records WHERE id=?", (rid,))
                removed += 1
            self._conn.commit()
        self._reclaim()
        return removed

    def clear_all(self, keep_files_ok: bool = False) -> dict[str, int]:
        """清空历史 + 删除所有截图文件。"""
        with self._lock:
            shots_deleted = 0
            if not keep_files_ok:
                for p in list(self.shots.glob("*")):
                    if p.is_file():
                        try:
                            p.unlink()
                            shots_deleted += 1
                        except OSError as e:
                            log.warning("删除文件失败 %s: %s", p, e)
            rows = int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])
            self._conn.execute("DELETE FROM records")
            self._conn.commit()
        self._reclaim()
        return {"records": rows, "files": shots_deleted}

    # ------------------------------------------------------------ 对账 / 维护

    def trim_history(self, limit: int) -> int:
        """只保留最新 limit 条，超出部分连同其截图一并删除。"""
        if limit <= 0:
            return 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, image_path FROM records ORDER BY id DESC LIMIT -1 OFFSET ?", (int(limit),)
            ).fetchall()
        if not rows:
            return 0
        return self.delete_records([r["id"] for r in rows])

    def reconcile(self, drop_orphans: bool | None = None) -> dict[str, int]:
        """双向对账：清孤儿图片、清失效图片引用。"""
        drop = self.drop_orphan if drop_orphans is None else drop_orphans
        orphan_deleted = 0
        dangling_cleared = 0

        with self._lock:
            rows = self._conn.execute(
                "SELECT id, image_path FROM records WHERE image_path IS NOT NULL AND image_path <> ''"
            ).fetchall()
            referenced: set[str] = {r["image_path"].replace("\\", "/") for r in rows}

            # 1) 数据库有记录但文件丢了 → 清空引用（保留答案文本）
            for r in rows:
                p = self.abs_shot_path(r["image_path"])
                if p is None or not p.exists():
                    self._conn.execute("UPDATE records SET image_path=NULL WHERE id=?", (r["id"],))
                    dangling_cleared += 1
            if dangling_cleared:
                self._conn.commit()

            # 2) 磁盘有文件但没有任何记录引用 → 删除
            if drop:
                for p in list(self.shots.glob("*")):
                    if not p.is_file():
                        continue
                    rel = f"shots/{p.name}"
                    if rel not in referenced:
                        try:
                            p.unlink()
                            orphan_deleted += 1
                        except OSError as e:
                            log.warning("删除孤儿文件失败 %s: %s", p, e)

        if orphan_deleted or dangling_cleared:
            log.info("对账完成：删除孤儿图片 %d，清理失效引用 %d", orphan_deleted, dangling_cleared)
        return {"orphan_deleted": orphan_deleted, "dangling_cleared": dangling_cleared}

    def stats(self) -> dict[str, int]:
        with self._lock:
            records = int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])
        files = [p for p in self.shots.glob("*") if p.is_file()]
        return {
            "records": records,
            "files": len(files),
            "bytes": sum(p.stat().st_size for p in files if p.exists()),
        }

    def data_dir_size(self) -> int:
        root = self.db_file.parent
        total = 0
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    continue
        return total

    def _reclaim(self) -> None:
        """回收磁盘页，避免删数据后文件不缩小。"""
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.execute("VACUUM")
            except sqlite3.Error as e:
                log.debug("回收空间失败: %s", e)
