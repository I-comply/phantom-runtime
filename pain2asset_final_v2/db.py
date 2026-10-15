import sqlite3
import os
from contextlib import closing
from typing import Dict, Any, List

class DatabaseManager:
    def __init__(self, db_path: str = "data/pain2asset.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with closing(self._get_connection()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS packages (
                    package_id TEXT PRIMARY KEY,
                    asset_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    marketing_copy TEXT NOT NULL,
                    marketplaces TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pain_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    author TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    detected_at TIMESTAMP NOT NULL,
                    UNIQUE (source_name, source_url, title)
                );
            """)
            conn.commit()

    def save_package(self, pkg: Dict[str, Any]) -> None:
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO packages (package_id, asset_name, category, description, marketing_copy, marketplaces, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pkg["package_id"],
                    pkg["asset_name"],
                    pkg["category"],
                    pkg["description"],
                    pkg["marketing_copy"],
                    ",".join(pkg["optimal_marketplaces"]),
                    pkg["status"],
                    pkg["created_at"].isoformat(),
                ),
            )
            conn.commit()

    def save_pain_point(self, source_name: str, source_url: str, title: str, description: str, author: str, severity: str, detected_at: str) -> None:
        with closing(self._get_connection()) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO pain_points (source_name, source_url, title, description, author, severity, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (source_name, source_url, title, description, author, severity, detected_at),
            )
            conn.commit()

    def get_recent_pain_points(self, limit: int = 50) -> List[Dict[str, Any]]:
        with closing(self._get_connection()) as conn:
            cursor = conn.execute("SELECT * FROM pain_points ORDER BY detected_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]
