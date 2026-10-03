"""/api/talk — stub, filled in by its phase (docs/TASKS.md)."""
from fastapi import APIRouter, Depends

from .. import auth

router = APIRouter(prefix="/talk", dependencies=[Depends(auth.require_auth)], tags=["talk"])
