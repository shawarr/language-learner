"""Router registry. Add new routers here; main.py mounts every one under /api."""
from . import auth, system, voice

ALL_ROUTERS = [auth.router, system.router, voice.router]
