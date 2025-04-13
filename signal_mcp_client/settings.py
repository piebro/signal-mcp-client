import sqlite3
import json
import threading
from contextlib import contextmanager
import os
import copy

DEFAULT_SETTINGS_DB_PATH = "user_settings.db"
_db_write_lock = threading.Lock()

SETTINGS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS user_settings (
        session_id TEXT PRIMARY KEY NOT NULL,
        settings TEXT NOT NULL DEFAULT '{}'
    );
"""

AVAILABLE_MODELS = ["claude-3-7-sonnet-latest", "claude-3-5-haiku-latest", "mistral/mistral-large-latest"]

DEFAULT_SETTINGS = {
    "system_prompt": "None",
    "model_name": AVAILABLE_MODELS[0],
    "llm_chat_message_context_limit": 30,
}

SETTINGS_DB_PATH = "settings.db"


def initialize_settings_database():
    """
    Ensures the settings database file and the user_settings table exist.
    Should be called once when the application starts.
    """
    print(f"Initializing settings database at: {SETTINGS_DB_PATH}")
    # Ensure the directory exists
    db_dir = os.path.dirname(SETTINGS_DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
        print(f"Created directory: {db_dir}")

    # Use a separate lock for initialization safety, though less critical here
    init_lock = threading.Lock()
    with init_lock:
        conn = None
        try:
            # Use check_same_thread=True for init safety as it's likely single-threaded call
            conn = sqlite3.connect(SETTINGS_DB_PATH, check_same_thread=True)
            cursor = conn.cursor()
            cursor.execute(SETTINGS_TABLE_SQL)
            conn.commit()
            print("Settings database initialized successfully with 'user_settings' table.")
        except sqlite3.Error as e:
            print(f"Settings database initialization error: {e}")
            raise
        finally:
            if conn:
                conn.close()


@contextmanager
def get_settings_db_connection():
    """Provides a database connection ensuring it's closed."""
    # Allow connections from multiple threads
    conn = sqlite3.connect(SETTINGS_DB_PATH, check_same_thread=False)
    # No need for row_factory=sqlite3.Row as we fetch specific columns simply
    try:
        yield conn, conn.cursor()
    except sqlite3.Error as e:
        print(f"Settings database error: {e}")
        conn.rollback()  # Rollback on database errors
        raise
    except Exception as e:
        print(f"An unexpected error occurred with settings DB: {e}")
        conn.rollback()  # Rollback on other errors during yield
        raise
    finally:
        # Ensure connection is closed regardless of success or failure
        if conn:
            conn.close()


def get_settings(session_id):
    settings_dict = copy.copy(DEFAULT_SETTINGS)
    try:
        with get_settings_db_connection() as (conn, cursor):
            cursor.execute("SELECT settings FROM user_settings WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if row and row[0]:
                settings_dict.update(json.loads(row[0]))
    except sqlite3.Error as db_err:
        print(f"Database error fetching settings for session {session_id}: {db_err}")
    except Exception as e:
        print(f"Unexpected error fetching settings for session {session_id}: {e}")
    return settings_dict


def update_settings(session_id, **kwargs):
    with _db_write_lock:
        try:
            with get_settings_db_connection() as (conn, cursor):
                current_settings = get_settings(session_id)

                for setting_name, setting_value in kwargs.items():
                    if setting_name in DEFAULT_SETTINGS:
                        current_settings[setting_name] = setting_value

                updated_settings_json = json.dumps(current_settings)
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO user_settings (session_id, settings)
                    VALUES (?, ?)
                    """,
                    (session_id, updated_settings_json),
                )
                conn.commit()

        except sqlite3.Error as db_err:
            print(f"Database error updating settings for session {session_id}: {db_err}")
            raise
        except Exception as e:
            print(f"Unexpected error updating settings for session {session_id}: {e}")
            raise


def reset_settings(session_id):
    update_settings(session_id, **DEFAULT_SETTINGS)