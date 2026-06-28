"""Messages router stub (Fase 0).

In Fase 0 the real endpoint lives under /chats/{chat_id}/messages (see chats router).
This module is reserved for future sub-resources (e.g. /messages/{id} for edits/deletes).
"""
from fastapi import APIRouter

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/{message_id}", status_code=501)
async def get_message(message_id: int):
    return {"detail": "Not implemented in phase 0"}
