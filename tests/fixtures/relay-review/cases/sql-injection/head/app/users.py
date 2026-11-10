import sqlite3


def get_user(conn: sqlite3.Connection, user_id: int):
    return conn.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()


def search_users(conn: sqlite3.Connection, name: str):
    """Users whose name starts with `name`."""
    query = f"SELECT id, name FROM users WHERE name LIKE '{name}%'"
    return conn.execute(query).fetchall()
