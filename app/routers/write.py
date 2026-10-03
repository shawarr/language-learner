"""/api/write — a writing task from the current unit, feedback on the text, and the recent pieces."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import auth
from ..services import writing

router = APIRouter(prefix="/write", dependencies=[Depends(auth.require_auth)], tags=["write"])


class SubmitBody(BaseModel):
    prompt: str = ""
    text: str


@router.get("/prompt")
async def prompt():
    return await writing.new_prompt()


@router.post("/submit")
async def submit(body: SubmitBody):
    try:
        return await writing.submit(body.prompt, body.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/recent")
async def recent(limit: int = Query(10, ge=1, le=100)):
    return {"items": await writing.recent(limit)}
