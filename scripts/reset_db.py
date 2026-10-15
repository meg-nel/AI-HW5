"""Reset the working database to the original values.

Copies data/campus_customs_original.db (the untouched file we were given) over
data/campus_customs_new.db, the working copy the agents read and update. The MCP server
re-creates its own helper tables (approvals, drafts) the next time it opens the database.

Run from the project root:  .venv\\Scripts\\python scripts\\reset_db.py
"""

import hashlib
import shutil
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT / "data" / "campus_customs_original.db"
WORKING = ROOT / "data" / "campus_customs_new.db"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reset_database() -> str:
    """Overwrite the working copy with the original. Returns the working copy's hash."""
    if not ORIGINAL.exists():
        raise FileNotFoundError(f"Original database missing: {ORIGINAL}")
    for extra in (WORKING.with_name(WORKING.name + "-wal"), WORKING.with_name(WORKING.name + "-shm")):
        extra.unlink(missing_ok=True)
    shutil.copyfile(ORIGINAL, WORKING)
    WORKING.chmod(stat.S_IREAD | stat.S_IWRITE)  # the original is read-only; the working copy must not be
    digest = sha256(WORKING)
    if digest != sha256(ORIGINAL):
        raise RuntimeError("Reset failed: working copy does not match the original")
    return digest


if __name__ == "__main__":
    print(f"Reset {WORKING.relative_to(ROOT)} from {ORIGINAL.name} (sha256 {reset_database()[:12]}...)")
