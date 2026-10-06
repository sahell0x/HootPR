import os


def get_user(conn, uid):
    return conn.execute(f"select * from users where id = {uid}")
