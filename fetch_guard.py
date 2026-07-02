"""
Validation guard for catalog refreshes.

Every fetcher should write to a temp file and call safe_replace() instead of
overwriting a catalog directly. The guard refuses the swap when the new file
is malformed or suspiciously smaller than the old one, so one bad upstream
day (an HTML error page, a truncated download, a moved endpoint) can't
silently destroy a good catalog and get committed by an automated run.

We have seen this fail mode for real: UCDP once returned a 50-line HTML page
with a 200 status where the CSV should have been.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd


class GuardError(Exception):
    pass


def safe_replace(new_path: str | Path, target_path: str | Path,
                   required_cols: list[str] | None = None,
                   min_rows_ratio: float = 0.98,
                   keep_backup: bool = True) -> int:
    """Validate new_path, then atomically replace target_path with it.

    Checks, in order:
      1. new file parses as CSV (catches HTML error pages, truncation)
      2. required_cols all present (catches schema changes upstream)
      3. row count >= min_rows_ratio * old row count (catches partial
         downloads; catalogs here are append-mostly, so shrinking more than
         a couple percent means something is wrong, not that history changed)

    On success: old file saved to <target>.bak (if keep_backup), new file
    moved into place. Returns the new row count.
    On failure: raises GuardError and leaves the target untouched.
    """
    new_path, target_path = Path(new_path), Path(target_path)

    try:
        new_df = pd.read_csv(new_path, low_memory=False)
    except Exception as e:
        raise GuardError(f"{new_path.name}: does not parse as CSV ({e})")

    if required_cols:
        missing = [c for c in required_cols if c not in new_df.columns]
        if missing:
            raise GuardError(
                f"{new_path.name}: missing expected column(s) {missing}; "
                f"upstream schema may have changed")

    if target_path.exists():
        try:
            old_rows = len(pd.read_csv(target_path, low_memory=False))
        except Exception:
            old_rows = 0  # old file unreadable — replacing it is an upgrade
        floor = int(old_rows * min_rows_ratio)
        if len(new_df) < floor:
            raise GuardError(
                f"{new_path.name}: {len(new_df)} rows < guard floor {floor} "
                f"(old file has {old_rows}); refusing to shrink the catalog")
        if keep_backup and old_rows:
            shutil.copy2(target_path, target_path.with_suffix(
                target_path.suffix + ".bak"))

    shutil.move(str(new_path), str(target_path))
    return len(new_df)


def guard_or_exit(new_path, target_path, required_cols=None, **kw) -> int:
    """safe_replace, but print + exit(1) on failure (for script use)."""
    try:
        n = safe_replace(new_path, target_path, required_cols, **kw)
        print(f"  OK {Path(target_path).name}: {n} rows (guard passed)")
        return n
    except GuardError as e:
        print(f"  GUARD REFUSED: {e}", file=sys.stderr)
        Path(new_path).unlink(missing_ok=True)
        sys.exit(1)
