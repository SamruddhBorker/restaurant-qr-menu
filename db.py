"""SQLite storage for menu items and live stock. Standard library only."""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price_paise INTEGER NOT NULL,
  veg INTEGER NOT NULL DEFAULT 0,
  stock INTEGER,                       -- NULL = unlimited, otherwise portions left
  available INTEGER NOT NULL DEFAULT 1,-- staff "86" switch
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

FIELDS = ("category", "name", "description", "price_paise", "veg", "stock",
          "available", "sort_order")


def clean_item(data: dict, partial: bool = False) -> dict:
    """Validate and normalise item input. Raises ValueError with a readable message."""
    out: dict[str, Any] = {}

    def want(k: str) -> bool:
        return k in data or not partial

    def text(k: str, lo: int, hi: int, default: Optional[str] = None) -> str:
        v = data.get(k, default)
        if v is None:
            raise ValueError(f"{k} is required")
        v = str(v).strip()
        if not lo <= len(v) <= hi:
            raise ValueError(f"{k} must be {lo}-{hi} characters")
        return v

    def integer(k: str, lo: int, hi: int, default: Optional[int] = None) -> int:
        v = data.get(k, default)
        if isinstance(v, bool) or v is None:
            raise ValueError(f"{k} must be a number")
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ValueError(f"{k} must be a number") from None
        if not lo <= n <= hi:
            raise ValueError(f"{k} must be between {lo} and {hi}")
        return n

    if want("name"):
        out["name"] = text("name", 1, 80)
    if want("category"):
        out["category"] = text("category", 1, 40)
    if want("description"):
        out["description"] = text("description", 0, 200, "")
    if want("price_paise"):
        out["price_paise"] = integer("price_paise", 0, 10_000_000)
    if want("veg"):
        out["veg"] = 1 if integer("veg", 0, 1, 0) else 0
    if want("available"):
        out["available"] = 1 if integer("available", 0, 1, 1) else 0
    if want("sort_order"):
        out["sort_order"] = integer("sort_order", -1000, 100000, 0)
    if "stock" in data or not partial:
        out["stock"] = None if data.get("stock") in (None, "") else integer("stock", 0, 9999)
    return out


class MenuDB:
    def __init__(self, path: str = ":memory:", low_threshold: int = 5) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.low = low_threshold
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('version','1')")

    # ---- helpers
    def _status(self, r: sqlite3.Row) -> str:
        if not r["available"] or r["stock"] == 0:
            return "sold_out"
        if r["stock"] is not None and r["stock"] <= self.low:
            return "low"
        return "available"

    def _item(self, r: sqlite3.Row) -> dict:
        d = {k: r[k] for k in ("id",) + FIELDS}
        d["veg"] = bool(d["veg"])
        d["available"] = bool(d["available"])
        d["status"] = self._status(r)
        return d

    def _bump(self) -> None:
        self.db.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key='version'")

    # ---- reads
    def version(self) -> int:
        with self.lock:
            return int(self.db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])

    def list_items(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM items ORDER BY sort_order, category, id").fetchall()
        return [self._item(r) for r in rows]

    def get(self, item_id: int) -> Optional[dict]:
        with self.lock:
            r = self.db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return self._item(r) if r else None

    def count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    # ---- writes
    def create(self, data: dict) -> dict:
        c = clean_item(data)
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO items(category,name,description,price_paise,veg,stock,available,sort_order) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (c["category"], c["name"], c["description"], c["price_paise"], c["veg"],
                 c["stock"], c["available"], c["sort_order"]))
            self._bump()
            new_id = cur.lastrowid
        return self.get(new_id)

    def update(self, item_id: int, data: dict) -> Optional[dict]:
        c = clean_item(data, partial=True)
        if c:
            cols = ", ".join(f"{k}=?" for k in c)
            with self.lock:
                cur = self.db.execute(f"UPDATE items SET {cols} WHERE id=?",
                                      (*c.values(), item_id))
                if cur.rowcount:
                    self._bump()
        return self.get(item_id)

    def delete(self, item_id: int) -> bool:
        with self.lock:
            cur = self.db.execute("DELETE FROM items WHERE id=?", (item_id,))
            if cur.rowcount:
                self._bump()
            return cur.rowcount == 1

    def sold_one(self, item_id: int):
        """Take one portion off the stock. Returns the item, None if missing, 'none_left' if at 0."""
        with self.lock:
            r = self.db.execute("SELECT stock FROM items WHERE id=?", (item_id,)).fetchone()
            if r is None:
                return None
            if r["stock"] is not None:
                cur = self.db.execute(
                    "UPDATE items SET stock=stock-1 WHERE id=? AND stock>0", (item_id,))
                if cur.rowcount == 0:
                    return "none_left"
                self._bump()
        return self.get(item_id)

    def seed(self, items: list[dict]) -> None:
        for it in items:
            self.create(it)
