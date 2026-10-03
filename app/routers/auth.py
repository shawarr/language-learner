from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from .. import auth

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginBody, response: Response):
    if not auth.check_password(body.password):
        raise HTTPException(status_code=401, detail="wrong password")
    auth.set_cookie(response)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    auth.clear_cookie(response)
    return {"ok": True}


@router.get("/me", dependencies=[Depends(auth.require_auth)])
async def me():
    return {"ok": True}
