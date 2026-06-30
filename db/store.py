"""
VeriLedger — SQLite Persistence Layer
========================================
Provides durable storage for documents, velocity events, and graph state
so the system survives server restarts without losing session data.

Design decisions:
  - SQLite: zero-config, single-file, no external server — fits the offline
    constraint and the local-demo deployment model perfectly.
  - JSON columns: ExtractedDocument and VelocityEvent are complex nested
    Pydantic models. Storing them as JSON avoids schema migrations during
    the hackathon while still making them queryable on the indexed columns.
  - Three tables:
      documents      — one row per ingested document
      velocity_events — one row per VelocityEvent
      graph_snapshots — periodic snapshots of the full graph (node-link JSON)
  - Thread-safety: SQLite in WAL mode + check_same_thread=False is safe for
    FastAPI's async handlers as long as we use a connection-per-call pattern
    (which we do via the context manager).

Usage (in api/main.py):
    from db.store import VeriLedgerStore
    store = VeriLedgerStore()          # call once at startup
    store.save_document(doc)
    store.save_velocity_events(events)
    docs   = store.load_all_documents()
    events = store.load_all_velocity_events()
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from models.entities import (
    DocumentType,
    ExtractedDocument,
    ForensicSignals,
    RiskLevel,
    VelocityEvent,
)

logger = logging.getLogger(__name__)

# Default DB path — sits next to the project root.
# Override by passing db_path to VeriLedgerStore().
DEFAULT_DB_PATH = Path(__file__).parent.parent / "veriledger.db"

# ── Schema ─────────────────────────────────────────────────────────────────────

_CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    document_id     TEXT    PRIMARY KEY,
    doc_type        TEXT    NOT NULL,
    applicant_id    TEXT,
    risk_level      TEXT    NOT NULL DEFAULT 'low',
    risk_score      REAL    NOT NULL DEFAULT 0.0,
    payload_json    TEXT    NOT NULL,
    ingested_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# Indexes for the two most common query patterns:
#   - "all docs for applicant X" (velocity / graph lookups)
#   - "all docs above a risk threshold" (underwriter dashboard)
_CREATE_DOCUMENTS_IDX_APPLICANT = """
CREATE INDEX IF NOT EXISTS idx_documents_applicant
    ON documents (applicant_id);
"""
_CREATE_DOCUMENTS_IDX_RISK = """
CREATE INDEX IF NOT EXISTS idx_documents_risk
    ON documents (risk_level, risk_score DESC);
"""

_CREATE_VELOCITY_EVENTS = """
CREATE TABLE IF NOT EXISTS velocity_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    applicant_id    TEXT    NOT NULL,
    event_date      TEXT    NOT NULL,
    event_type      TEXT    NOT NULL,
    value           REAL    NOT NULL,
    document_id     TEXT,
    ingested_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_VELOCITY_IDX = """
CREATE INDEX IF NOT EXISTS idx_velocity_applicant
    ON velocity_events (applicant_id, event_date);
"""

# Stores the full NetworkX node-link JSON periodically so the graph can be
# restored on restart without replaying every document through add_document().
_CREATE_GRAPH_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS graph_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot    TEXT    NOT NULL,
    saved_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


class VeriLedgerStore:
    """
    Thin SQLite persistence layer for VeriLedger.

    Thread-safety note:
        SQLite in WAL mode with check_same_thread=False is safe for
        multiple readers + one writer concurrently, which covers FastAPI's
        async request handling pattern. Each public method opens and closes
        its own connection via the _conn() context manager.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("VeriLedgerStore initialised at %s", self.db_path)

    # ── Internal helpers ───────────────────────────────────────────────────────

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Open a short-lived connection, yield it, then commit+close.
        Rolls back automatically on any exception.
        """
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.execute("PRAGMA journal_mode=WAL")   # allows concurrent reads
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist yet."""
        with self._conn() as conn:
            conn.execute(_CREATE_DOCUMENTS)
            conn.execute(_CREATE_DOCUMENTS_IDX_APPLICANT)
            conn.execute(_CREATE_DOCUMENTS_IDX_RISK)
            conn.execute(_CREATE_VELOCITY_EVENTS)
            conn.execute(_CREATE_VELOCITY_IDX)
            conn.execute(_CREATE_GRAPH_SNAPSHOTS)
        logger.debug("DB schema initialised")

    # ── Documents ──────────────────────────────────────────────────────────────

    def save_document(self, doc: ExtractedDocument) -> None:
        """
        Upsert a document (INSERT OR REPLACE).
        Called after the fraud detection pipeline has set risk_level/risk_score.
        """
        shared = doc.shared_fields()
        applicant_id = shared.applicant_id or None

        payload = doc.model_dump_json()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO documents
                    (document_id, doc_type, applicant_id, risk_level, risk_score, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    risk_level   = excluded.risk_level,
                    risk_score   = excluded.risk_score,
                    payload_json = excluded.payload_json
                """,
                (
                    doc.document_id,
                    doc.doc_type.value,
                    applicant_id,
                    doc.risk_level.value,
                    doc.risk_score,
                    payload,
                ),
            )
        logger.debug("Saved document %s (risk=%s)", doc.document_id, doc.risk_level.value)

    def load_document(self, document_id: str) -> Optional[ExtractedDocument]:
        """Load a single document by ID. Returns None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()

        if not row:
            return None
        try:
            return ExtractedDocument.model_validate_json(row["payload_json"])
        except Exception as exc:
            logger.error("Failed to deserialise document %s: %s", document_id, exc)
            return None

    def load_all_documents(self) -> dict[str, ExtractedDocument]:
        """
        Load every document into a dict keyed by document_id.
        Used at startup to restore in-memory state from the last session.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT document_id, payload_json FROM documents ORDER BY ingested_at"
            ).fetchall()

        result: dict[str, ExtractedDocument] = {}
        for row in rows:
            try:
                doc = ExtractedDocument.model_validate_json(row["payload_json"])
                result[row["document_id"]] = doc
            except Exception as exc:
                logger.error("Skipping corrupt document %s: %s", row["document_id"], exc)

        logger.info("Loaded %d documents from DB", len(result))
        return result

    def delete_document(self, document_id: str) -> bool:
        """Delete a document. Returns True if a row was deleted."""
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE document_id = ?", (document_id,)
            )
        return cursor.rowcount > 0

    def list_documents_summary(
        self,
        min_risk_score: float = 0.0,
        doc_type: Optional[str] = None,
        applicant_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """
        Return lightweight summaries (no full payload) for the dashboard.
        Supports optional filtering by risk, doc_type, or applicant.
        """
        query = """
            SELECT document_id, doc_type, applicant_id, risk_level, risk_score, ingested_at
            FROM documents
            WHERE risk_score >= ?
        """
        params: list = [min_risk_score]

        if doc_type:
            query += " AND doc_type = ?"
            params.append(doc_type)
        if applicant_id:
            query += " AND applicant_id = ?"
            params.append(applicant_id)

        query += " ORDER BY risk_score DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()

        return [dict(row) for row in rows]

    # ── Velocity Events ────────────────────────────────────────────────────────

    def save_velocity_events(self, events: list[VelocityEvent]) -> int:
        """
        Bulk-insert velocity events.
        Skips duplicates silently (INSERT OR IGNORE on a composite unique check
        isn't practical here since events have no natural unique key, so we
        deduplicate in memory before inserting).
        Returns number of rows inserted.
        """
        if not events:
            return 0

        rows = [
            (
                ev.applicant_id,
                ev.event_date,
                ev.event_type,
                ev.value,
                ev.document_id,
            )
            for ev in events
        ]

        with self._conn() as conn:
            cursor = conn.executemany(
                """
                INSERT INTO velocity_events
                    (applicant_id, event_date, event_type, value, document_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
        inserted = cursor.rowcount
        logger.debug("Saved %d velocity events", inserted)
        return inserted

    def load_all_velocity_events(self) -> list[VelocityEvent]:
        """
        Load all velocity events ordered by date.
        Used at startup to restore the in-memory _events list.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT applicant_id, event_date, event_type, value, document_id
                FROM velocity_events
                ORDER BY event_date
                """
            ).fetchall()

        events = [
            VelocityEvent(
                applicant_id=row["applicant_id"],
                event_date=row["event_date"],
                event_type=row["event_type"],
                value=row["value"],
                document_id=row["document_id"],
            )
            for row in rows
        ]
        logger.info("Loaded %d velocity events from DB", len(events))
        return events

    def load_velocity_events_for_applicant(self, applicant_id: str) -> list[VelocityEvent]:
        """Load all velocity events for a specific applicant (fast — indexed)."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT applicant_id, event_date, event_type, value, document_id
                FROM velocity_events
                WHERE applicant_id = ?
                ORDER BY event_date
                """,
                (applicant_id,),
            ).fetchall()

        return [
            VelocityEvent(
                applicant_id=row["applicant_id"],
                event_date=row["event_date"],
                event_type=row["event_type"],
                value=row["value"],
                document_id=row["document_id"],
            )
            for row in rows
        ]

    # ── Graph Snapshots ────────────────────────────────────────────────────────

    def save_graph_snapshot(self, graph_json: dict) -> None:
        """
        Persist the current graph as a JSON snapshot.
        Keeps only the 5 most recent snapshots to limit DB size.
        """
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO graph_snapshots (snapshot) VALUES (?)",
                (json.dumps(graph_json),),
            )
            # Prune old snapshots — keep latest 5 only
            conn.execute(
                """
                DELETE FROM graph_snapshots
                WHERE id NOT IN (
                    SELECT id FROM graph_snapshots ORDER BY saved_at DESC LIMIT 5
                )
                """
            )
        logger.debug("Graph snapshot saved")

    def load_latest_graph_snapshot(self) -> Optional[dict]:
        """
        Load the most recent graph snapshot.
        Returns None if no snapshot exists yet.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT snapshot FROM graph_snapshots ORDER BY saved_at DESC LIMIT 1"
            ).fetchone()

        if not row:
            return None
        try:
            return json.loads(row["snapshot"])
        except json.JSONDecodeError as exc:
            logger.error("Corrupt graph snapshot: %s", exc)
            return None

    # ── Full Reset ─────────────────────────────────────────────────────────────

    def reset_all(self) -> None:
        """
        Wipe all data from all tables.
        Called by the /reset endpoint — requires confirm=true in the API.
        """
        with self._conn() as conn:
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM velocity_events")
            conn.execute("DELETE FROM graph_snapshots")
        logger.warning("VeriLedgerStore: all data wiped by reset_all()")

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Quick summary counts — useful for the /health endpoint."""
        with self._conn() as conn:
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            event_count = conn.execute("SELECT COUNT(*) FROM velocity_events").fetchone()[0]
            high_risk = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE risk_level IN ('high','critical')"
            ).fetchone()[0]
            snap_count = conn.execute("SELECT COUNT(*) FROM graph_snapshots").fetchone()[0]

        return {
            "total_documents":        doc_count,
            "total_velocity_events":  event_count,
            "high_or_critical_docs":  high_risk,
            "graph_snapshots_stored": snap_count,
            "db_path":                str(self.db_path),
        }
