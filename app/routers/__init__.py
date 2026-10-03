"""Router registry. Add new routers here; main.py mounts every one under /api."""
from . import (auth, checkpoint, curriculum, drill, lesson, placement, progress, system, talk, vocab,
               voice, write)

ALL_ROUTERS = [auth.router, system.router, voice.router, lesson.router, talk.router, vocab.router,
               curriculum.router, placement.router, checkpoint.router, write.router, drill.router,
               progress.router]
