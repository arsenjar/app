"""
FastAPI server — serves both the Mini App static files AND the JSON API.

Run:
    uvicorn server:app --host 0.0.0.0 --port 8000

Then expose via HTTPS (ngrok, Cloudflare Tunnel, or a real VPS).
The public HTTPS URL goes into .env as WEBAPP_URL.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
from auth import verify_init_data

load_dotenv()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ALLOW_UNSAFE = os.environ.get("ALLOW_UNSAFE_DEV", "0") == "1"

WEBAPP_DIR = Path(__file__).parent / "webapp"

app = FastAPI(title="TaskFlow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],               # Telegram WebApps don't send Origin reliably
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()


# ── Auth dependency ───────────────────────────────────────────────────────

def get_user_id(request: Request, x_init_data: str | None = Header(default=None)) -> int:
    """
    Extract & validate user from Telegram initData header.
    DEV fallback: if ALLOW_UNSAFE_DEV=1 and ?uid=... is provided, use it (local testing only).
    """
    if x_init_data and BOT_TOKEN:
        user = verify_init_data(x_init_data, BOT_TOKEN)
        if user:
            return int(user["id"])

    # Dev fallback for local testing without Telegram wrapper
    if ALLOW_UNSAFE:
        uid = request.query_params.get("uid") or request.headers.get("X-Dev-Uid")
        if uid and uid.isdigit():
            return int(uid)

    raise HTTPException(status_code=401, detail="invalid initData")


# ── Schemas ───────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    type: str = Field(default="task", pattern="^(task|deadline|meeting)$")
    due_at: str | None = None                 # "YYYY-MM-DDTHH:MM"
    duration: int = Field(default=0, ge=0, le=1440)


class TaskUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    type: str | None = Field(default=None, pattern="^(task|deadline|meeting)$")
    due_at: str | None = None
    duration: int | None = Field(default=None, ge=0, le=1440)
    done: bool | None = None


# ── API ───────────────────────────────────────────────────────────────────

@app.get("/api/tasks")
def api_list(request: Request, x_init_data: str | None = Header(default=None)):
    uid = get_user_id(request, x_init_data)
    return db.list_tasks(uid)


@app.post("/api/tasks")
def api_create(
    payload: TaskCreate,
    request: Request,
    x_init_data: str | None = Header(default=None),
):
    uid = get_user_id(request, x_init_data)
    if not payload.text.strip():
        raise HTTPException(400, "text required")
    return db.create_task(
        user_id=uid,
        text=payload.text,
        task_type=payload.type,
        due_at=payload.due_at,
        duration=payload.duration,
    )


@app.patch("/api/tasks/{task_id}")
def api_update(
    task_id: int,
    payload: TaskUpdate,
    request: Request,
    x_init_data: str | None = Header(default=None),
):
    uid = get_user_id(request, x_init_data)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "done" in updates:
        updates["done"] = 1 if updates["done"] else 0
    updated = db.update_task(uid, task_id, **updates)
    if not updated:
        raise HTTPException(404, "not found")
    return updated


@app.delete("/api/tasks/{task_id}")
def api_delete(
    task_id: int,
    request: Request,
    x_init_data: str | None = Header(default=None),
):
    uid = get_user_id(request, x_init_data)
    ok = db.delete_task(uid, task_id)
    if not ok:
        raise HTTPException(404, "not found")
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}


# ── Static webapp (mounted LAST so /api/* takes priority) ─────────────────

if WEBAPP_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")
