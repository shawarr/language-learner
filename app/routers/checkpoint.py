"""/api/checkpoint — stub, filled in by its phase (docs/TASKS.md)."""
from fastapi import APIRouter, Depends

from .. import auth

router = APIRouter(prefix="/checkpoint", dependencies=[Depends(auth.require_auth)], tags=["checkpoint"])
