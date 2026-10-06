import sqlite3

conn = sqlite3.connect(":memory:")


def fetch_one(sql, *args):
    return conn.execute(sql, args).fetchone()
