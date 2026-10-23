#!/usr/bin/env python3
"""Concurrent openers of one LocalStateStore all succeed (the PR #647 WAL race, on main's store).

Switching a database to WAL upgrades the switcher's read lock to a write lock, and SQLite refuses
that upgrade with `database is locked` at once, never through the busy handler (waiting while
holding a read lock could deadlock). So when several processes open a FRESH store, or one written
in rollback-journal mode by an older schema, together, the losers of the switch died in
`_connect` however long `busy_timeout` was. The first opener's switch persists in the file, so a
loser backs off and re-reads the mode; schema creation and migration then run in one
`BEGIN IMMEDIATE` transaction, so openers take turns and each re-reads the columns under the lock.

Every child waits at a barrier (it prints `ready`, then blocks on stdin until all are ready), so
the openers really do race instead of being spread out by interpreter start-up.
"""
from __future__ import annotations

import importlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OPENER = (
    "import sys; sys.path.insert(0, sys.argv[1]);"
    "from runtime.providers.local_state import LocalStateStore;"
    "print('ready', flush=True); sys.stdin.readline();"
    "LocalStateStore(sys.argv[2], env={}); print('ok', flush=True)"
)

# A store written before the migrated columns existed: the base shape of two of the tables
# `_migrate` extends, in SQLite's default rollback-journal mode, holding one row.
OLD_SCHEMA = """
CREATE TABLE runs (id TEXT PRIMARY KEY, coordinator_handle TEXT, created_at REAL NOT NULL);
CREATE TABLE gates (
    gate_id TEXT PRIMARY KEY, run_id TEXT NOT NULL DEFAULT 'default', sender TEXT, recipient TEXT,
    question TEXT NOT NULL, options_json TEXT, status TEXT NOT NULL DEFAULT 'pending', answer TEXT,
    created_at REAL NOT NULL, resolved_at REAL
);
INSERT INTO runs (id, coordinator_handle, created_at) VALUES ('r-old', 'term_old', 0);
"""


def _ls():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module("runtime.providers.local_state")


def _columns(db: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


class ConcurrentOpen(unittest.TestCase):
    OPENERS = 8

    def _open_together(self, db: Path, count: int) -> None:
        procs = [
            subprocess.Popen([sys.executable, "-c", OPENER, str(ROOT), str(db)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(count)
        ]
        try:
            for p in procs:
                p.stdout.readline()  # the barrier: every child has imported and is waiting
            for p in procs:
                p.stdin.write("go\n")
                p.stdin.flush()
            results = [p.communicate(timeout=120) for p in procs]
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
                    p.wait()
        errors = [(err.strip().splitlines() or [f"exit {p.returncode}"])[-1]
                  for p, (_out, err) in zip(procs, results, strict=True) if p.returncode]
        self.assertEqual([p.returncode for p in procs], [0] * count, errors)

    def test_many_openers_of_a_fresh_store_all_succeed_round_after_round(self):
        # One round of eight lost an opener about half the time on main (4def361f69); six rounds
        # make a pass on the unfixed store a ~1-in-200 event.
        for _round in range(6):
            with tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "s.db"
                self._open_together(db, self.OPENERS)
                conn = sqlite3.connect(db)
                try:
                    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                finally:
                    conn.close()
                self.assertEqual(mode, "wal")
                self.assertIn("launch_intents", tables)

    def test_openers_racing_a_migration_all_succeed(self):
        wanted = {"task_id", "message_id", "prev_status", "kind"}
        for _round in range(4):
            with tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / "s.db"
                conn = sqlite3.connect(db)
                conn.executescript(OLD_SCHEMA)
                conn.close()
                self.assertFalse(wanted & _columns(db, "gates"))
                self._open_together(db, self.OPENERS)
                self.assertTrue(wanted <= _columns(db, "gates"), _columns(db, "gates"))
                self.assertIn("objective", _columns(db, "runs"))
                self.assertIn("gate_closed_at", _columns(db, "dispatches"))
                conn = sqlite3.connect(db)
                try:
                    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                    kept = conn.execute("SELECT id, coordinator_handle FROM runs").fetchall()
                finally:
                    conn.close()
                self.assertEqual(mode, "wal")
                self.assertEqual(kept, [("r-old", "term_old")])


class OneTransactionUpgrade(unittest.TestCase):
    def test_an_upgrade_that_fails_leaves_the_store_as_it_found_it(self):
        # executescript committed every CREATE before `_migrate` ran, so a migration that failed
        # left a half-upgraded store behind. A `gates` VIEW makes the first ALTER fail.
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "s.db"
            conn = sqlite3.connect(db)
            conn.executescript(
                "CREATE TABLE runs (id TEXT PRIMARY KEY, coordinator_handle TEXT, created_at REAL NOT NULL);"
                "CREATE VIEW gates AS SELECT 1 AS gate_id;"
            )
            conn.close()
            with self.assertRaises(sqlite3.OperationalError):
                _ls().LocalStateStore(db, env={})
            conn = sqlite3.connect(db)
            try:
                tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))
            finally:
                conn.close()
            self.assertEqual(tables, ["runs"])


class WalSwitchSettles(unittest.TestCase):
    def test_a_database_sqlite_keeps_out_of_wal_still_opens(self):
        # The back-off retries only a lock. A database SQLite will not put in WAL answers the
        # switch with its own mode and no error; that answer ends the loop instead of spinning.
        code = (
            "import sqlite3, sys; sys.path.insert(0, sys.argv[1]);"
            "from runtime.providers import local_state as m;"
            "conn = sqlite3.connect(':memory:', isolation_level=None);"
            "m._ensure_wal(conn, 30.0); print(conn.execute('PRAGMA journal_mode').fetchone()[0])"
        )
        proc = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True, timeout=20)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, "memory"), proc.stderr)

    def test_every_store_connection_waits_out_a_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _ls().LocalStateStore(Path(tmp) / "s.db", env={})
            with store._connect() as conn:
                self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")


if __name__ == "__main__":
    unittest.main()
