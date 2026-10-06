import hashlib

from api.db import fetch_one


def load_user(uid):
    row = fetch_one("select * from users where id = %s", uid)
    return normalize(row)


def save_user(payload):
    payload["password"] = hash_password(payload["password"])
    return payload


def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def list_orders(oid):
    return fetch_one("select * from orders where id = %s", oid)


def normalize(row):
    return dict(row or {})


def health_status():
    return {"ok": True}
