from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from ..domain.models import Declaration, DeclarationItem, Hint, Image, Point, Session

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  session_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, closed_at TEXT,
  operator TEXT, location TEXT, lighting TEXT, camera_model TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS declarations(
  declaration_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, items_json TEXT NOT NULL,
  created_at TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0, confirmed_at TEXT,
  arrangement_no INTEGER NOT NULL DEFAULT 1, copied_from TEXT);
CREATE TABLE IF NOT EXISTS images(
  image_id TEXT PRIMARY KEY, declaration_id TEXT NOT NULL, session_id TEXT NOT NULL,
  arrangement_no INTEGER NOT NULL, path TEXT NOT NULL, sha256 TEXT, width INTEGER, height INTEGER,
  content_type TEXT, captured_at TEXT NOT NULL, meta_json TEXT,
  tag_status TEXT NOT NULL DEFAULT 'untagged', tag_revision INTEGER NOT NULL DEFAULT 0,
  tagged_at TEXT, tagged_by TEXT);
CREATE INDEX IF NOT EXISTS ix_images_session ON images(session_id);
CREATE INDEX IF NOT EXISTS ix_images_decl ON images(declaration_id);
CREATE INDEX IF NOT EXISTS ix_images_date ON images(captured_at);
CREATE TABLE IF NOT EXISTS hints(
  image_id TEXT NOT NULL, instrument_uid TEXT NOT NULL, instance_no INTEGER NOT NULL,
  visible INTEGER NOT NULL, hint_source TEXT NOT NULL,
  center_json TEXT, end_a_json TEXT, end_b_json TEXT,
  occluded INTEGER NOT NULL, added_after_capture INTEGER NOT NULL,
  PRIMARY KEY(image_id, instrument_uid, instance_no));
"""


def _pt(p: Optional[Point]) -> Optional[str]:
    return None if p is None else json.dumps({"x": p.x, "y": p.y, "status": p.status})


def _unpt(s: Optional[str]) -> Optional[Point]:
    if not s:
        return None
    d = json.loads(s)
    return Point(d["x"], d["y"], d.get("status", "visible"))


class SqliteMetadataStore:
    def __init__(self, path: Path):
        self._path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self._path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- sessions
    def add_session(self, s: Session) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)",
                      (s.session_id, s.started_at, s.closed_at, s.operator, s.location, s.lighting, s.camera_model, s.notes))

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return None if r is None else Session(**dict(r))

    def update_session(self, s: Session) -> None:
        with self._conn() as c:
            c.execute("UPDATE sessions SET closed_at=?, operator=?, location=?, lighting=?, camera_model=?, notes=? WHERE session_id=?",
                      (s.closed_at, s.operator, s.location, s.lighting, s.camera_model, s.notes, s.session_id))

    # ---- declarations
    @staticmethod
    def _decl(r: sqlite3.Row) -> Declaration:
        return Declaration(
            declaration_id=r["declaration_id"], session_id=r["session_id"],
            items=[DeclarationItem(**i) for i in json.loads(r["items_json"])],
            created_at=r["created_at"], confirmed=bool(r["confirmed"]), confirmed_at=r["confirmed_at"],
            arrangement_no=r["arrangement_no"], copied_from=r["copied_from"])

    def add_declaration(self, d: Declaration) -> None:
        items = json.dumps([{"instrument_uid": i.instrument_uid, "count": i.count} for i in d.items])
        with self._conn() as c:
            c.execute("INSERT INTO declarations VALUES(?,?,?,?,?,?,?,?)",
                      (d.declaration_id, d.session_id, items, d.created_at, int(d.confirmed), d.confirmed_at,
                       d.arrangement_no, d.copied_from))

    def get_declaration(self, declaration_id: str) -> Optional[Declaration]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM declarations WHERE declaration_id=?", (declaration_id,)).fetchone()
        return None if r is None else self._decl(r)

    def update_declaration(self, d: Declaration) -> None:
        with self._conn() as c:
            c.execute("UPDATE declarations SET confirmed=?, confirmed_at=?, arrangement_no=? WHERE declaration_id=?",
                      (int(d.confirmed), d.confirmed_at, d.arrangement_no, d.declaration_id))

    def list_declarations(self, session_id: Optional[str] = None) -> list[Declaration]:
        with self._conn() as c:
            if session_id:
                rows = c.execute("SELECT * FROM declarations WHERE session_id=? ORDER BY created_at", (session_id,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM declarations ORDER BY created_at").fetchall()
        return [self._decl(r) for r in rows]

    # ---- images
    @staticmethod
    def _img(r: sqlite3.Row) -> Image:
        d = dict(r)
        d["meta"] = json.loads(d.pop("meta_json") or "{}")
        return Image(**d)

    def add_image(self, i: Image) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (i.image_id, i.declaration_id, i.session_id, i.arrangement_no, i.path, i.sha256, i.width, i.height,
                       i.content_type, i.captured_at, json.dumps(i.meta, ensure_ascii=False), i.tag_status, i.tag_revision,
                       i.tagged_at, i.tagged_by))

    def get_image(self, image_id: str) -> Optional[Image]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM images WHERE image_id=?", (image_id,)).fetchone()
        return None if r is None else self._img(r)

    def update_image(self, i: Image) -> None:
        with self._conn() as c:
            c.execute("UPDATE images SET tag_status=?, tag_revision=?, tagged_at=?, tagged_by=? WHERE image_id=?",
                      (i.tag_status, i.tag_revision, i.tagged_at, i.tagged_by, i.image_id))

    def list_images(self, *, session_id=None, declaration_id=None, tag_status=None, date=None,
                    limit: int = 200, offset: int = 0) -> list[Image]:
        where, args = [], []
        for col, val in (("session_id", session_id), ("declaration_id", declaration_id), ("tag_status", tag_status)):
            if val:
                where.append(f"{col}=?"); args.append(val)
        if date:
            where.append("substr(captured_at,1,10)=?"); args.append(date)
        sql = "SELECT * FROM images" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY captured_at LIMIT ? OFFSET ?"
        with self._conn() as c:
            rows = c.execute(sql, (*args, limit, offset)).fetchall()
        return [self._img(r) for r in rows]

    # ---- hints
    @staticmethod
    def _hint(r: sqlite3.Row) -> Hint:
        return Hint(instrument_uid=r["instrument_uid"], instance_no=r["instance_no"], visible=bool(r["visible"]),
                    hint_source=r["hint_source"], center=_unpt(r["center_json"]), end_a=_unpt(r["end_a_json"]),
                    end_b=_unpt(r["end_b_json"]), occluded=bool(r["occluded"]),
                    added_after_capture=bool(r["added_after_capture"]))

    def replace_hints(self, image_id: str, hints: list[Hint]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM hints WHERE image_id=?", (image_id,))
            c.executemany("INSERT INTO hints VALUES(?,?,?,?,?,?,?,?,?,?)", [
                (image_id, h.instrument_uid, h.instance_no, int(h.visible), h.hint_source,
                 _pt(h.center), _pt(h.end_a), _pt(h.end_b), int(h.occluded), int(h.added_after_capture)) for h in hints])

    def list_hints(self, image_id: str) -> list[Hint]:
        return self.list_hints_for_images([image_id]).get(image_id, [])

    def list_hints_for_images(self, image_ids: list[str]) -> dict[str, list[Hint]]:
        out: dict[str, list[Hint]] = {}
        if not image_ids:
            return out
        with self._conn() as c:
            for k in range(0, len(image_ids), 500):
                chunk = image_ids[k:k + 500]
                q = ",".join("?" * len(chunk))
                for r in c.execute(f"SELECT * FROM hints WHERE image_id IN ({q}) ORDER BY instrument_uid, instance_no", chunk):
                    out.setdefault(r["image_id"], []).append(self._hint(r))
        return out
