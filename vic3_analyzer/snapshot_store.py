"""Transactional, content-addressed modules shared by every export view."""
from __future__ import annotations

import hashlib
import ast
import json
import sqlite3
import zlib
from pathlib import Path


def code_version(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted([root / 'analyze.py', * (root / 'vic3_analyzer').glob('*.py')]):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def extraction_version(root: Path) -> str:
    """UI/report wording changes must not invalidate parsed world modules."""
    source = (root / 'analyze.py').read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    digest = hashlib.sha256()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom)) or (
            isinstance(node, ast.FunctionDef) and (node.name.startswith('parse_') or node.name in {
                'meta', 'num', 'brace_span', 'database_block', 'top_value', 'top_values',
                'list_value', 'subblock', 'trend_stats', 'battle_side_stats', 'empty_pop_stats',
                'country_label_for_tag', 'building_category', 'iter_top_blocks', 'iter_numbered_entries'})):
            digest.update(ast.dump(node, include_attributes=False).encode('utf-8'))
    for name in ('parser_core', 'metrics', 'pops', 'buildings', 'states', 'diplomacy', 'country_names', 'world_data', 'snapshot_store'):
        digest.update((root / 'vic3_analyzer' / (name + '.py')).read_bytes())
    return digest.hexdigest()


class SnapshotStore:
    def __init__(self, root: Path, snapshot: str, version: str):
        root.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(root / 'snapshots.sqlite', timeout=60)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS objects (
                digest TEXT PRIMARY KEY, payload BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS modules (
                snapshot TEXT, version TEXT, name TEXT, digest TEXT,
                PRIMARY KEY(snapshot, version, name));
            CREATE TABLE IF NOT EXISTS dependencies (
                version TEXT, name TEXT, signature TEXT, digest TEXT,
                PRIMARY KEY(version, name, signature));
        ''')
        self.snapshot, self.version = snapshot, version

    def get(self, name, signature=None):
        row = self.connection.execute('''SELECT o.digest, o.payload FROM modules m
            JOIN objects o ON o.digest=m.digest
            WHERE m.snapshot=? AND m.version=? AND m.name=?''',
            (self.snapshot, self.version, name)).fetchone()
        if row is None and signature:
            row = self.connection.execute('''SELECT o.digest, o.payload FROM dependencies d
                JOIN objects o ON o.digest=d.digest
                WHERE d.version=? AND d.name=? AND d.signature=?''',
                (self.version, name, signature)).fetchone()
            if row:
                with self.connection:
                    self.connection.execute('INSERT OR REPLACE INTO modules VALUES (?, ?, ?, ?)',
                        (self.snapshot, self.version, name, row[0]))
        if row is None:
            return None
        try:
            payload = zlib.decompress(row[1])
            if hashlib.sha256(payload).hexdigest() != row[0]:
                return None
            return json.loads(payload)
        except (zlib.error, ValueError, UnicodeError):
            return None

    def put(self, name, value, signature=None):
        payload = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        digest = hashlib.sha256(payload).hexdigest()
        with self.connection:
            self.connection.execute('INSERT INTO objects VALUES (?, ?) ON CONFLICT(digest) DO UPDATE SET payload=excluded.payload',
                                    (digest, zlib.compress(payload, level=1)))
            self.connection.execute('INSERT OR REPLACE INTO modules VALUES (?, ?, ?, ?)',
                                    (self.snapshot, self.version, name, digest))
            if signature:
                self.connection.execute('INSERT OR REPLACE INTO dependencies VALUES (?, ?, ?, ?)',
                                       (self.version, name, signature, digest))

    def close(self):
        self.connection.close()
