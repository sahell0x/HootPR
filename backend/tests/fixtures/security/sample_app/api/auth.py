def get_current_user(token: str = ""):
    if not token:
        raise PermissionError("unauthenticated")
    return {"token": token}
