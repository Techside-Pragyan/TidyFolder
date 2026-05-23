import sqlite3
import os
from pathlib import Path

# Resolve the database path relative to the backend directory
DB_DIR = Path(__file__).resolve().parent.parent
DB_PATH = DB_DIR / "tidyfolder.db"

def get_db_connection():
    """Establishes and returns a connection to the SQLite database."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Access columns by name like a dictionary
    return conn

def init_db():
    """Initializes the database and creates the necessary tables if they don't exist."""
    print(f"Initializing database at: {DB_PATH}")
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Settings Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # 2. Scan History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_path TEXT NOT NULL,
            total_files INTEGER DEFAULT 0,
            total_size INTEGER DEFAULT 0,
            space_freed INTEGER DEFAULT 0,
            health_score REAL DEFAULT 100.0,
            scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 3. Cleanup History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cleanup_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            category TEXT NOT NULL,
            action_taken TEXT NOT NULL,  -- 'delete', 'archive', 'move'
            backup_path TEXT,            -- path if backed up
            cleaned_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 4. Recommendations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            category TEXT NOT NULL,
            reason TEXT NOT NULL,        -- 'duplicate', 'junk', 'large', 'old'
            recommendation_type TEXT NOT NULL, -- 'delete', 'compress', 'organize'
            recommended_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 5. File Metadata Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS file_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER,
            file_path TEXT UNIQUE,
            file_name TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            category TEXT NOT NULL,      -- 'Images', 'Documents', etc.
            is_duplicate INTEGER DEFAULT 0,
            is_junk INTEGER DEFAULT 0,
            last_modified DATETIME,
            last_accessed DATETIME,
            FOREIGN KEY(scan_id) REFERENCES scan_history(id) ON DELETE CASCADE
        )
    """)

    # Insert default settings if they do not exist
    default_settings = [
        ("theme", "cyberpunk"),
        ("safe_delete", "true"),      # Moves to Recycle Bin or Backup instead of direct deletion
        ("auto_scan", "false"),       # Real-time scan / watchdog sorted
        ("backup_dir", str(DB_DIR / "backups")),
        ("schedule_frequency", "never") # 'daily', 'weekly', 'never'
    ]
    for key, val in default_settings:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))

    # Ensure backups directory exists
    backup_dir = DB_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)

    conn.commit()
    conn.close()
    print("Database initialization completed successfully.")

if __name__ == "__main__":
    init_db()
