from app.db import get_user


class Base:
    pass


class UserService(Base):
    def __init__(self, conn):
        self.conn = conn

    def show(self, uid):
        return get_user(self.conn, uid)
