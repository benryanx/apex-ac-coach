from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, StrictBool
from typing import Literal
from starlette.middleware.trustedhost import TrustedHostMiddleware
from websockets.asyncio.client import connect as websocket_connect

from .engine import CoachEngine
from .telemetry import ACReader, DemoReader, Sample
from .opponents import OpponentBridge

ROOT = Path(__file__).resolve().parent.parent
VOICE_NAMES = tuple(json.loads((ROOT / 'web' / 'voices.json').read_text(encoding='utf-8')))
def engineer_instructions():
    personality=json.loads((ROOT/'web'/'engineer-personality.json').read_text(encoding='utf-8'))
    return '\n\n'.join(personality['instructions'])


class Offer(BaseModel):
    sdp: str = Field(min_length=10, max_length=65536)
    voice: str = "cedar"

    @field_validator('voice')
    @classmethod
    def available_voice(cls, value):
        if value not in VOICE_NAMES:
            raise ValueError('Choose an available engineer voice.')
        return value


class Settings(BaseModel):
    api_key: str = Field(min_length=10, max_length=500)


class Mode(BaseModel):
    mode: str = Field(pattern="^(ac|demo)$")


class CloseRequest(BaseModel):
    confirmed: bool = False



class DisplaySettings(BaseModel):
    version: Literal[1] = 1
    preset: Literal['drive','race','minimal','review','custom'] = 'drive'
    order: Literal['drive','race','minimal','review'] = 'drive'
    density: Literal['compact','comfortable'] = 'compact'
    transparent: bool = True
    opacity: int = Field(default=100,ge=60,le=100)
    widgets: dict[str,StrictBool] = Field(default_factory=dict,max_length=8)
    parts: dict[str,StrictBool] = Field(default_factory=dict,max_length=12)
    collapsed: dict[str,StrictBool] = Field(default_factory=dict,max_length=8)


async def finalize_session(session_id, key):
    """Close through a documented trusted sideband, including on window exit."""
    async with asyncio.timeout(10):
        async with websocket_connect(
            f"wss://api.openai.com/v1/live/sessions/{session_id}/attach",
            additional_headers={"Authorization": f"Bearer {key}"}, open_timeout=5,
        ) as ws:
            await ws.send(json.dumps({"type": "session.close", "event_id": secrets.token_hex(16)}))
            async for raw in ws:
                event = json.loads(raw)
                if event.get("type") == "session.closed":
                    return
                if event.get("type") == "error":
                    raise RuntimeError("Live session close was rejected")
    raise RuntimeError("Live session finalization was not confirmed")


def create_app(demo=False, data_dir=None):
    display_path=(Path(data_dir) if data_dir else ROOT/'data')/'display.json'
    reader = DemoReader() if demo else ACReader()
    engine = CoachEngine(Path(data_dir) if data_dir else ROOT / "data")
    bridge = None
    state = {"telemetry": Sample().dict(), "analysis": {}, "map": [], "events": [], "laps": []}
    token = secrets.token_urlsafe(32)
    runtime = {"key": os.environ.get("OPENAI_API_KEY", ""), "mode": "demo" if demo else "ac", "live_ids": set(), "creating": False}

    async def poll():
        nonlocal state
        while True:
            try:
                state = engine.update(bridge.enrich(reader.read()))
                state["mode"] = runtime["mode"]
            except (OSError, ValueError):
                logging.exception("Telemetry read failed")
                state = engine.update(Sample(status="disconnected"))
            await asyncio.sleep(0.05)

    async def close_sessions():
        for session_id in list(runtime["live_ids"]):
            try:
                await finalize_session(session_id, runtime["key"])
            except Exception:
                logging.warning("Could not close Live session during shutdown")

    @asynccontextmanager
    async def lifespan(app):
        nonlocal bridge
        bridge = OpponentBridge(config_path=ROOT/'data'/'bridge.json')
        task = asyncio.create_task(poll())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await close_sessions()
        bridge.close()
        if hasattr(reader, "close"):
            reader.close()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            allowed = {f"http://127.0.0.1:{request.url.port}", f"http://localhost:{request.url.port}"}
            if request.headers.get("x-coach-token") != token or (origin and origin not in allowed):
                return JSONResponse({"detail": "Unexpected local request"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (ROOT / "web" / "index.html").read_text(encoding="utf-8").replace("__COACH_TOKEN__", token)

    @app.get("/api/config")
    async def config():
        return {"key_configured": bool(runtime["key"]), "model": "gpt-live-1", "mode": runtime["mode"]}

    @app.get('/api/display')
    async def get_display():
        try:
            return DisplaySettings.model_validate_json(display_path.read_text(encoding='utf-8')).model_dump()
        except (OSError,ValueError):
            return None

    @app.post('/api/display')
    async def save_display(settings: DisplaySettings):
        display_path.parent.mkdir(parents=True,exist_ok=True)
        temp=display_path.with_suffix('.tmp')
        temp.write_text(settings.model_dump_json(),encoding='utf-8');temp.replace(display_path)
        return {'saved':True}

    @app.get("/api/state")
    async def get_state():
        return state

    @app.get("/api/events")
    async def stream(request: Request):
        async def generate():
            while not await request.is_disconnected():
                yield f"data: {json.dumps(state, allow_nan=False)}\n\n"
                await asyncio.sleep(0.2)
        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/api/key")
    async def set_key(settings: Settings):
        if runtime["live_ids"] or runtime["creating"]:
            raise HTTPException(409, "Disconnect the engineer before changing the API key.")
        runtime["key"] = settings.api_key.strip()
        return {"configured": True}

    @app.post("/api/mode")
    async def set_mode(body: Mode):
        nonlocal reader, engine
        if runtime["live_ids"] or runtime["creating"]:
            raise HTTPException(409, "Disconnect the engineer before switching telemetry sources.")
        if hasattr(reader, "close"):
            reader.close()
        reader = DemoReader() if body.mode == "demo" else ACReader()
        engine = CoachEngine(Path(data_dir) if data_dir else ROOT / "data")
        runtime["mode"] = body.mode
        return {"mode": body.mode}

    @app.get("/api/export")
    async def export():
        return JSONResponse(engine.export(), headers={"Content-Disposition": 'attachment; filename="apex-session.json"'})

    @app.post("/api/live/session")
    async def live_session(offer: Offer):
        if not runtime["key"]:
            raise HTTPException(503, "Add your OpenAI API key in Settings to connect the engineer.")
        if runtime["live_ids"] or runtime["creating"]:
            raise HTTPException(409, "A voice session is already active. Disconnect it before reconnecting.")
        runtime["creating"] = True
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post("https://api.openai.com/v1/live/sessions",
                    headers={"Authorization": f"Bearer {runtime['key']}"},
                    json={"session": {"model": "gpt-live-1", "instructions": engineer_instructions(),
                        "audio": {"output": {"voice": offer.voice}},
                        "delegation": {"type": "client"}},
                        "transport": {"type": "webrtc", "sdp": offer.sdp}})
            if response.status_code >= 400:
                raise HTTPException(response.status_code, f"OpenAI rejected the voice connection ({response.status_code}). Check your API key, model access and billing.")
            result = response.json()
            runtime["live_ids"].add(result["session"]["id"])
            return result
        except httpx.HTTPError:
            raise HTTPException(502, "Could not reach OpenAI. Check the network and retry.")
        finally:
            runtime["creating"] = False

    @app.post("/api/live/close/{session_id}")
    async def close_session(session_id: str, body: CloseRequest):
        if session_id not in runtime["live_ids"]:
            return {"closed": True}
        if not body.confirmed:
            try:
                await finalize_session(session_id, runtime["key"])
            except Exception:
                raise HTTPException(502, "Session closure could not be confirmed. Retry disconnect.")
        runtime["live_ids"].discard(session_id)
        return {"closed": True}

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app
