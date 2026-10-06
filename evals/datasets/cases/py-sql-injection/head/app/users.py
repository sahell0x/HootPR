import sqlite3


def get_user(conn: sqlite3.Connection, user_id: int):
    return conn.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()


def find_by_name(conn: sqlite3.Connection, name: str):
    query = f"SELECT id, name FROM users WHERE name = '{name}'"
    return conn.execute(query).fetchall()
