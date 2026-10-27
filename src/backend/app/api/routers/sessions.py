from __future__ import annotations
from fastapi import APIRouter, Request

from ..schemas import DeclarationIn, DeclarationOut, SessionIn, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201)
def start_session(request: Request, body: SessionIn):
    return SessionOut.of(request.app.state.c.capture.start_session(**body.model_dump()))


@router.get("/{session_id}", response_model=SessionOut)
def get_session(request: Request, session_id: str):
    return SessionOut.of(request.app.state.c.capture.get_session(session_id))


@router.post("/{session_id}/close", response_model=SessionOut)
def close_session(request: Request, session_id: str):
    return SessionOut.of(request.app.state.c.capture.close_session(session_id))


@router.get("/{session_id}/declarations", response_model=list[DeclarationOut])
def list_declarations(request: Request, session_id: str):
    return [DeclarationOut.of(d) for d in request.app.state.c.capture.list_declarations(session_id)]


@router.post("/{session_id}/declarations", response_model=DeclarationOut, status_code=201)
def create_declaration(request: Request, session_id: str, body: DeclarationIn):
    items = [item.instrument_uid for item in body.items]
    return DeclarationOut.of(request.app.state.c.capture.create_declaration(session_id, items, body.copy_from))
