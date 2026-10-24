"""/api/game/* and /api/leaderboard — XP, rings, badges and the head-to-head totals."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import auth, users
from ..services import game

router = APIRouter(dependencies=[Depends(auth.require_auth)], tags=["game"])


class SeenIn(BaseModel):
    badge_ids: list[str] = []


@router.get("/game/me")
async def me():
    return await game.me()


@router.post("/game/seen")
async def seen(body: SeenIn):
    await game.mark_seen(users.user_id(), body.badge_ids)
    return {"ok": True}


@router.get("/leaderboard")
async def leaderboard():
    return await game.leaderboard()
