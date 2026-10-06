from fastapi import APIRouter, Depends, FastAPI

from api.auth import get_current_user
from api.service import health_status, list_orders, load_user, save_user

app = FastAPI()
router = APIRouter(prefix="/orders")


@app.get("/users/{uid}")
def read_user(uid: int, user=Depends(get_current_user)):
    return load_user(uid)


@app.post("/users")
def create_user(payload: dict):
    return save_user(payload)


@router.get("/{oid}")
def read_order(oid: int):
    return list_orders(oid)


@app.get("/health")
def health():
    return health_status()


app.include_router(router)
