"""/api/progress — the whole progress page in one call."""
from fastapi import APIRouter, Depends

from .. import auth
from ..services import progress

router = APIRouter(prefix="/progress", dependencies=[Depends(auth.require_auth)], tags=["progress"])


@router.get("")
async def page():
    return await progress.payload()
