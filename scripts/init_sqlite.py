from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import SQLITE_DB_PATH
from backend.app.services.sqlite_service import migrate_json_to_sqlite


def main() -> None:
    migrate_json_to_sqlite()
    print(f"SQLite database ready: {SQLITE_DB_PATH}")


if __name__ == "__main__":
    main()
