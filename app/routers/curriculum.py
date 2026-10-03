"""/api/curriculum — the CEFR path and where the learner is on it."""
from fastapi import APIRouter, Depends

from .. import auth
from ..services import curriculum, profile

router = APIRouter(prefix="/curriculum", dependencies=[Depends(auth.require_auth)], tags=["curriculum"])


@router.get("")
async def tree():
    """The whole tree (without checkpoint tasks) plus the current position, for the progress page."""
    p = await profile.get_profile()
    cur = await curriculum.current()
    phases = [{**ph, "units": [curriculum.public_unit(u) for u in ph["units"]]} for ph in curriculum.phases()]
    return {"version": curriculum.load().get("version", 1), "phases": phases,
            "current": {"phase_id": cur["phase"]["id"], "unit_id": cur["unit"]["id"], "level": p["level"],
                        "placement_done": bool(p["placement_done"])}}


@router.get("/current")
async def current():
    from ..services import checkpoint  # late import: checkpoint depends on curriculum

    cur = await curriculum.current()
    cur["checkpoint_available"] = await checkpoint.is_available(cur["unit"]["id"])
    return cur
