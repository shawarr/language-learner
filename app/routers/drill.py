"""/api/drill — items generated from his own mistakes, graded one at a time or all at once."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import auth
from ..services import drills

router = APIRouter(prefix="/drill", dependencies=[Depends(auth.require_auth)], tags=["drill"])


class AnswerBody(BaseModel):
    index: int
    answer: str


class SubmitBody(BaseModel):
    answers: list[str | None]


@router.get("/new")
async def new(n: int | None = Query(None)):
    return await drills.new(n)


@router.post("/{drill_id}/answer")
async def answer(drill_id: int, body: AnswerBody):
    try:
        return await drills.answer(drill_id, body.index, body.answer)
    except LookupError:
        raise HTTPException(status_code=404, detail="no such drill")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{drill_id}/submit")
async def submit(drill_id: int, body: SubmitBody):
    try:
        return await drills.submit(drill_id, body.answers)
    except LookupError:
        raise HTTPException(status_code=404, detail="no such drill")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
