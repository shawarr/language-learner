"""The Learn mode: coursework for the current unit. See docs/API.md."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth
from ..services import curriculum, exercises, lesson_ask, lessons

router = APIRouter(prefix="/lesson", dependencies=[Depends(auth.require_auth)], tags=["lesson"])


class StepBody(BaseModel):
    step: int = Field(ge=0, le=200)


class CheckBody(BaseModel):
    step: int = Field(ge=0, le=200)
    correct: bool


class AskTurn(BaseModel):
    q: str = Field(max_length=lesson_ask.MAX_QUESTION_CHARS)
    a: str = Field(max_length=2000)


class AskBody(BaseModel):
    unit_id: str = Field(max_length=40)
    exercise: dict
    picked: str | None = Field(default=None, max_length=300)
    question: str = Field(min_length=1, max_length=lesson_ask.MAX_QUESTION_CHARS)
    history: list[AskTurn] = Field(default_factory=list, max_length=lesson_ask.MAX_HISTORY)


async def _lesson_payload(unit_id: str, seed: int = 0) -> dict:
    lesson = lessons.for_unit(unit_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="No lesson for this unit yet.")
    # The client walks `exercises`: the authored teaching with generated practice interleaved.
    # `steps` stays in the payload so the lesson can still be read straight through.
    return {"unit_id": unit_id, "lesson": lesson, "exercises": exercises.build(lesson, seed),
            "progress": await lessons.progress(unit_id)}


@router.get("/current")
async def current(seed: int = 0):
    """The lesson for the unit he is on, with where he stopped."""
    cur = await curriculum.current()
    unit_id = cur["unit"]["id"]
    lesson = lessons.for_unit(unit_id)
    if lesson is None:
        # Later units have no coursework written yet; say so plainly rather than 404-ing the tab.
        return {"unit_id": unit_id, "unit_title": cur["unit"]["title"], "lesson": None,
                "progress": await lessons.progress(unit_id),
                "detail": "The written lesson for this unit is not ready yet — the practice modes still work."}
    return {**await _lesson_payload(unit_id, seed), "unit_title": cur["unit"]["title"]}


@router.get("/status")
async def status():
    cur = await curriculum.current()
    return await lessons.status_for(cur["unit"]["id"])


@router.get("/overview")
async def overview():
    """Every unit of the current phase: lesson, progress, and whether it is open (Learn's path)."""
    cur = await curriculum.current()
    phase = curriculum.phase(cur["phase"]["id"]) or {"units": []}
    return {"units": await lessons.overview([u["id"] for u in phase["units"]])}


@router.post("/ask")
async def ask(body: AskBody):
    """"Ask about this": one model call about the screen the learner is on."""
    if curriculum.unit(body.unit_id) is None:
        raise HTTPException(status_code=404, detail="No such unit.")
    if not lesson_ask.exercise_size_ok(body.exercise):
        raise HTTPException(status_code=413, detail="That screen is too large to ask about.")
    try:
        return await lesson_ask.ask(body.unit_id, body.exercise, body.picked, body.question,
                                    [t.model_dump() for t in body.history])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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


@router.post("/{unit_id}/restart")
async def restart(unit_id: str):
    """Back to step one, keeping the completion. Progress itself never moves backwards."""
    await _lesson_payload(unit_id)
    return await lessons.restart(unit_id)


@router.post("/{unit_id}/complete")
async def finish(unit_id: str):
    await _lesson_payload(unit_id)
    return await lessons.complete(unit_id)
