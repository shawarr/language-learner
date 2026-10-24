"""Login as one of the two learners. The picker needs the public list; nothing else is open."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from .. import auth, users

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class AvatarBody(BaseModel):
    avatar: str


@router.get("/users")
async def list_users():
    """Names and avatars for the login picker — never anything secret."""
    return {"users": await users.list_public(), "avatars": users.AVATARS}


@router.post("/login")
async def login(body: LoginBody, response: Response):
    user = await users.authenticate(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="wrong password")
    auth.set_cookie(response, user["id"])
    return {"ok": True, "user": users.public(user)}


@router.post("/logout")
async def logout(response: Response):
    auth.clear_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(auth.require_auth)):
    return {"ok": True, "user": users.public(user), "avatars": users.AVATARS}


@router.post("/avatar")
async def avatar(body: AvatarBody, user: dict = Depends(auth.require_auth)):
    try:
        return {"ok": True, "user": await users.set_avatar(user["id"], body.avatar)}
    except ValueError:
        raise HTTPException(status_code=422, detail="unknown avatar")
