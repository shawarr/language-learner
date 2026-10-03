"""The Learn mode: coursework for the current unit. See docs/API.md."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth
from ..services import curriculum, lessons

router = APIRouter(prefix="/lesson", dependencies=[Depends(auth.require_auth)], tags=["lesson"])


class StepBody(BaseModel):
    step: int = Field(ge=0, le=200)


class CheckBody(BaseModel):
    step: int = Field(ge=0, le=200)
    correct: bool


async def _lesson_payload(unit_id: str) -> dict:
    lesson = lessons.for_unit(unit_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="No lesson for this unit yet.")
    return {"unit_id": unit_id, "lesson": lesson, "progress": await lessons.progress(unit_id)}


@router.get("/current")
async def current():
    """The lesson for the unit he is on, with where he stopped."""
    cur = await curriculum.current()
    unit_id = cur["unit"]["id"]
    lesson = lessons.for_unit(unit_id)
    if lesson is None:
        # Later units have no coursework written yet; say so plainly rather than 404-ing the tab.
        return {"unit_id": unit_id, "unit_title": cur["unit"]["title"], "lesson": None,
                "progress": await lessons.progress(unit_id),
                "detail": "The written lesson for this unit is not ready yet — the practice modes still work."}
    return {**await _lesson_payload(unit_id), "unit_title": cur["unit"]["title"]}


@router.get("/status")
async def status():
    cur = await curriculum.current()
    return await lessons.status_for(cur["unit"]["id"])


@router.get("/{unit_id}")
async def one(unit_id: str):
    return await _lesson_payload(unit_id)


@router.post("/{unit_id}/progress")
async def save(unit_id: str, body: StepBody):
    await _lesson_payload(unit_id)
    return await lessons.save_step(unit_id, body.step)


@router.post("/{unit_id}/check")
async def check(unit_id: str, body: CheckBody):
    await _lesson_payload(unit_id)
    return await lessons.record_check(unit_id, body.correct)


@router.post("/{unit_id}/complete")
async def finish(unit_id: str):
    await _lesson_payload(unit_id)
    return await lessons.complete(unit_id)
