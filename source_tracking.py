"""Content-based provenance for refreshes; row counts alone miss revisions."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def file_digest(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sqlite_digest(path: str | Path, tables: list[str]) -> str | None:
    """Hash ordered logical rows, ignoring SQLite journal/page-layout churn."""
    path = Path(path)
    if not path.exists():
        return None
    h = hashlib.sha256()
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as con:
        con.execute('BEGIN')  # consistent snapshot across tables
        for table in sorted(tables):
            if not table.replace('_', '').isalnum():
                raise ValueError('Invalid table name')
            schema = con.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',
                                 ('table', table)).fetchone()
            if not schema:
                continue
            columns = con.execute(f'PRAGMA table_info("{table}")').fetchall()
            keys = [x[1] for x in sorted(columns, key=lambda x: x[5]) if x[5]]
            order = ','.join('"' + k.replace('"', '""') + '"' for k in keys) or 'rowid'
            h.update(json.dumps([table, schema[0]]).encode())
            for row in con.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
                h.update(json.dumps(row, default=str, allow_nan=False, separators=(',', ':')).encode())
                h.update(b'\n')
    return h.hexdigest()


def collect_fingerprints(root: str | Path = '.') -> dict:
    root = Path(root)
    result = {}
    for path in sorted((root / 'data').rglob('*')):
        if not path.is_file() or path.suffix not in {'.csv', '.json', '.gz'}:
            continue
        if path.name == 'catalog_counts.json' or path.name.startswith('_'):
            continue
        result[str(path.relative_to(root))] = file_digest(path)
    for name, path, tables in [
        ('earthquakes_modern', root / '../earthquakes/quakes.sqlite', ['quakes', 'significant_quakes']),
        ('earthquakes_historical', root / '../earthquakes/quakes_1900.sqlite', ['quakes']),
        ('spaceweather', root / '../spaceweather/spaceweather.sqlite', ['silso_daily', 'gfz_daily']),
    ]:
        result[name] = sqlite_digest(path, tables)
        for suffix in ['.coverage.json', '.significant.status.json']:
            metadata = Path(str(path) + suffix)
            result[name + suffix] = file_digest(metadata) if metadata.exists() else None
    return result


def changed_groups(previous: dict, current: dict) -> tuple[bool, bool, bool]:
    changed = {k for k in set(previous) | set(current) if previous.get(k) != current.get(k)}
    return (bool(changed), any(k.startswith('earthquakes_') for k in changed),
            any(k.startswith('spaceweather') for k in changed))


def write_json_if_changed(path: str | Path, payload: dict) -> bool:
    path = Path(path)
    content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(content)
    temp.replace(path)
    return True
