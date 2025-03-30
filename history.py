import sqlite3
import json
import threading
from contextlib import contextmanager

_db_write_lock = threading.Lock()

HISTORY_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        message_num INTEGER NOT NULL,
        message TEXT NOT NULL, -- Stores the full message as JSON
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id, message_num) -- Ensures message order integrity per session
    );
"""

INDEX_HISTORY_TABLE_SQL = """
    CREATE INDEX IF NOT EXISTS idx_chat_history_session_num
    ON chat_history (session_id, message_num);
"""

HISTORY_DB_PATH = "chat_history.db"


def initialize_database():
    """
    Ensures the database file and the single chat_history table exist.
    Should be called once when the application starts.
    """
    print(f"Initializing database at: {HISTORY_DB_PATH}")
    # Use a separate lock for initialization
    init_lock = threading.Lock()
    with init_lock:
        try:
            # Use check_same_thread=True for init safety
            conn = sqlite3.connect(HISTORY_DB_PATH, check_same_thread=True)
            cursor = conn.cursor()
            cursor.execute(HISTORY_TABLE_SQL)
            cursor.execute(INDEX_HISTORY_TABLE_SQL)
            conn.commit()
            print("Database initialized successfully with 'chat_history' table.")
        except sqlite3.Error as e:
            print(f"Database initialization error: {e}")
            raise
        finally:
            if conn:
                conn.close()


@contextmanager
def get_db_connection():
    """Provides a database connection ensuring it's closed."""
    conn = sqlite3.connect(HISTORY_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn, conn.cursor()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        conn.rollback()
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def add_message(session_id, message):
    """
    Add a message to the history, storing the entire message object as JSON.
    
    Args:
        session_id: The session identifier
        message: Dict containing the complete message in OpenAI format
    """
    message_json = json.dumps(message)
    
    with _db_write_lock:
        with get_db_connection() as (conn, cursor):
            try:
                # Find the next message_num for this session
                cursor.execute("SELECT MAX(message_num) FROM chat_history WHERE session_id = ?", (session_id,))
                max_num = cursor.fetchone()[0]
                next_message_num = (max_num + 1) if max_num is not None else 0
                
                # Insert the new message
                cursor.execute(
                    """
                    INSERT INTO chat_history (session_id, message_num, message)
                    VALUES (?, ?, ?)
                    """,
                    (session_id, next_message_num, message_json),
                )
                
                conn.commit()
                
            except sqlite3.Error as e:
                print(f"Error during add_message ({session_id}): {e}")
                conn.rollback()
                raise


def get_history(session_id, limit):
    """
    Retrieve chat history for a session.
    Returns a list of message objects in chronological order.
    
    Args:
        session_id: The session identifier
        limit: Optional maximum number of messages to retrieve
    """
    history = []
    with get_db_connection() as (conn, cursor):
        query = """
            SELECT message FROM (
                SELECT message, message_num
                FROM chat_history
                WHERE session_id = ?
                ORDER BY message_num DESC
                LIMIT ?
            ) ORDER BY message_num ASC;
        """
        params = (session_id, limit)
        cursor.execute(query, params)
        
        for row in cursor.fetchall():
            message = json.loads(row["message"])
            history.append(message)
            
    return history


def clear_history(session_id):
    """
    Deletes all history entries for a specific session_id.
    """
    with _db_write_lock:
        with get_db_connection() as (conn, cursor):
            try:
                cursor.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
                deleted_count = cursor.rowcount
                conn.commit()
                if deleted_count > 0:
                    print(f"History cleared successfully for session {session_id}. Deleted {deleted_count} entries.")
                else:
                    print(f"No history found to clear for session {session_id}.")
            except sqlite3.Error as e:
                print(f"Error clearing history for session {session_id}: {e}")
                conn.rollback()
                raise


def add_user_message(session_id, content, images_data_url):
    content_for_message = []
    if content:
        content_for_message.append({"type": "text", "text": content})
    if images_data_url:
        for image_data_url in images_data_url:
            content_for_message.append({"type": "image_url", "image_url": {"url": image_data_url}})

    if len(content_for_message) > 0:
        message = {"role": "user", "content": content_for_message}
        add_message(session_id, message)


def add_assistant_message(session_id, content, tool_calls=None):
    """Add a simple assistant text message."""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        temp_tool_calls = []
        for tool_call in tool_calls:
            temp_tool_calls.append({
                "id": tool_call.id,
                "type": "function",
                "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments}
            })
        message["tool_calls"] = temp_tool_calls
    add_message(session_id, message)


def add_tool_response(session_id, tool_call_id, name, content):
    """Add a tool response message."""
    message = {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content
    }
    add_message(session_id, message)