from fastapi import APIRouter, Depends

from api.auth import require_admin

router = APIRouter()


@router.get("/admin/users")
def list_users(_: None = Depends(require_admin)):
    return {"users": []}


@router.delete("/admin/users/{user_id}")
def delete_user(user_id: int):
    return {"deleted": user_id}
