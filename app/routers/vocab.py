"""/api/vocab — tap-to-translate, the vocabulary list, and the SRS review queue (docs/API.md)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import auth
from ..services import vocab

router = APIRouter(prefix="/vocab", dependencies=[Depends(auth.require_auth)], tags=["vocab"])


class TranslateBody(BaseModel):
    word: str
    context: str = ""


class AddBody(BaseModel):
    word: str
    translation: str
    example: str = ""
    source: str = "manual"


@router.post("/translate")
async def translate(body: TranslateBody):
    try:
        return await vocab.translate(body.word, body.context)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("")
async def add(body: AddBody):
    try:
        vid, created = await vocab.upsert(body.word, body.translation, body.example, body.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": vid, "word": vocab.clean_word(body.word), "created": created}


@router.get("")
async def browse(q: str = "", sort: str = Query("due", pattern="^(due|word|created)$"),
                 limit: int = Query(50, ge=1, le=500)):
    items, total = await vocab.search(q, sort, limit)
    return {"items": items, "total": total}


@router.delete("/{vocab_id}")
async def delete(vocab_id: int):
    if not await vocab.delete(vocab_id):
        raise HTTPException(status_code=404, detail="no such word")
    return {"ok": True}
