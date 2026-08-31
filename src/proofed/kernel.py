from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .subject import canonical_json


class KernelError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_event(prev_hash: str, run_id: str, event_type: str, payload: dict[str, Any], created_at: str) -> str:
    value = {
        "prevHash": prev_hash,
        "runId": run_id,
        "eventType": event_type,
        "payload": payload,
        "createdAt": created_at,
    }
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _initial_state(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": payload["runId"],
        "projectId": payload["projectId"],
        "projectRoot": payload["projectRoot"],
        "intent": payload["intent"],
        "intentRevision": 1,
        "phase": "WORKING",
        "active": True,
        "completionRequested": False,
        "requiredEvidence": payload["requiredEvidence"],
        "testCommands": payload["testCommands"],
        "testEvidence": {},
        "missingEvidence": list(payload["requiredEvidence"]),
        "failedPathRefs": [],
        "effects": [],
        "hookBlocks": {},
        "lastHookHandshake": None,
        "decision": None,
        "reason": None,
        "nextLegalAction": "finish the task, then run proofed verify",
        "subjectDigest": None,
        "receiptPath": None,
    }


def _reduce(state: dict[str, Any] | None, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type == "RUN_STARTED":
        if state is not None:
            raise KernelError("RUN_STARTED may only initialize a run")
        return _initial_state(payload)
    if state is None:
        raise KernelError("event precedes RUN_STARTED")
    result = json.loads(json.dumps(state))
    if event_type == "VERIFICATION_REQUESTED":
        result["phase"] = "VERIFYING"
        result["completionRequested"] = True
        result["subjectDigest"] = payload["subjectDigest"]
    elif event_type == "TEST_EVIDENCE_RECORDED":
        result["testEvidence"][payload["subjectDigest"]] = payload["evidence"]
    elif event_type == "VERIFICATION_DECIDED":
        result["decision"] = payload["decision"]
        result["reason"] = payload["reason"]
        result["missingEvidence"] = payload["missingEvidence"]
        result["nextLegalAction"] = payload["nextLegalAction"]
        result["subjectDigest"] = payload["subjectDigest"]
        result["receiptPath"] = payload["receiptPath"]
        if payload["decision"] == "PASSED":
            result["phase"] = "PASSED"
            result["active"] = False
        elif payload["decision"] == "HOLD":
            result["phase"] = "HOLD"
        else:
            result["phase"] = "VERIFYING"
    elif event_type == "HOOK_HANDSHAKE":
        result["lastHookHandshake"] = payload
    elif event_type == "HOOK_BLOCKED":
        key = payload["budgetKey"]
        result["hookBlocks"][key] = int(result["hookBlocks"].get(key, 0)) + 1
    elif event_type == "HOLD_RECORDED":
        result["phase"] = "HOLD"
        result["reason"] = payload["reason"]
        result["nextLegalAction"] = payload["nextLegalAction"]
    elif event_type == "RUN_CANCELLED":
        result["phase"] = "CANCELLED"
        result["active"] = False
    else:
        raise KernelError(f"unsupported canonical event: {event_type}")
    return result


class Kernel:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.data_dir = self.root / ".proofed"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "state.db"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS states (
                    run_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    active INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
                CREATE INDEX IF NOT EXISTS idx_states_active ON states(active, updated_at);
                """
            )

    def _verify_chain(self, connection: sqlite3.Connection) -> None:
        prev = "0" * 64
        for row in connection.execute("SELECT * FROM events ORDER BY seq"):
            payload = json.loads(row["payload_json"])
            expected = _hash_event(prev, row["run_id"], row["event_type"], payload, row["created_at"])
            if row["prev_hash"] != prev or row["event_hash"] != expected:
                raise KernelError("canonical event chain is corrupt; refusing to continue")
            prev = row["event_hash"]

    def _replay(self, connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
        state: dict[str, Any] | None = None
        rows = connection.execute("SELECT event_type, payload_json FROM events WHERE run_id=? ORDER BY seq", (run_id,))
        for row in rows:
            state = _reduce(state, row["event_type"], json.loads(row["payload_json"]))
        if state is None:
            raise KernelError(f"run not found: {run_id}")
        return state

    def _check_materialized(self, connection: sqlite3.Connection, run_id: str, state: dict[str, Any]) -> None:
        row = connection.execute("SELECT state_json, state_hash FROM states WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KernelError("materialized state is missing")
        encoded = canonical_json(state)
        digest = hashlib.sha256(encoded).hexdigest()
        if row["state_hash"] != digest or json.loads(row["state_json"]) != state:
            raise KernelError("materialized state diverges from replay; refusing to continue")

    def load(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            self._verify_chain(connection)
            state = self._replay(connection, run_id)
            self._check_materialized(connection, run_id, state)
            return state

    def active_run(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            self._verify_chain(connection)
            row = connection.execute(
                "SELECT run_id FROM states WHERE active=1 ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            state = self._replay(connection, row["run_id"])
            self._check_materialized(connection, row["run_id"], state)
            return state

    def append(self, run_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_chain(connection)
            last = connection.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = last["event_hash"] if last else "0" * 64
            created = _now()
            event_hash = _hash_event(prev, run_id, event_type, payload, created)
            connection.execute(
                "INSERT INTO events(run_id,event_type,payload_json,created_at,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
                (run_id, event_type, canonical_json(payload).decode("utf-8"), created, prev, event_hash),
            )
            state = self._replay(connection, run_id)
            encoded = canonical_json(state)
            state_hash = hashlib.sha256(encoded).hexdigest()
            connection.execute(
                """
                INSERT INTO states(run_id,state_json,state_hash,active,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    state_hash=excluded.state_hash,
                    active=excluded.active,
                    updated_at=excluded.updated_at
                """,
                (run_id, encoded.decode("utf-8"), state_hash, 1 if state["active"] else 0, created),
            )
            connection.commit()
            return state

    def start_run(
        self,
        *,
        project_id: str,
        intent: str,
        required_evidence: list[str],
        test_commands: list[list[str]],
    ) -> dict[str, Any]:
        existing = self.active_run()
        if existing:
            return existing
        run_id = str(uuid.uuid4())
        return self.append(
            run_id,
            "RUN_STARTED",
            {
                "runId": run_id,
                "projectId": project_id,
                "projectRoot": str(self.root),
                "intent": intent,
                "requiredEvidence": required_evidence,
                "testCommands": test_commands,
            },
        )

