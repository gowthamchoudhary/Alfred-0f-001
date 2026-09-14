"""Alfred accounts — deliberately simple email + password auth.

No OAuth providers by design: GitHub is an integration inside the product,
never the login provider. Passwords are stored as salted PBKDF2 hashes.
Sessions are opaque random tokens delivered as httpOnly cookies; only the
SHA-256 hash of each token is persisted, so a database leak cannot be
replayed as a login.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from .db import Database

SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
COOKIE_NAME = "alfred_session"
_PBKDF2_ITERATIONS = 240_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(candidate.hex(), digest_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_user(db: Database, request: Request) -> dict[str, Any] | None:
    """Return the signed-in user for this request, or None."""
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        return None
    return db.get_session_user(_token_hash(token))


def create_auth_router(db: Database) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    def _require_user(request: Request) -> dict[str, Any]:
        user = current_user(db, request)
        if not user:
            raise HTTPException(status_code=401, detail="not signed in")
        return user

    # Cookie transport defaults fit the same-origin sandbox preview (plain
    # http). A SPLIT deployment — frontend on Vercel/hosting, backend on a
    # different site — must set ALFRED_COOKIE_SAMESITE=none and
    # ALFRED_COOKIE_SECURE=1, or browsers silently drop the session cookie on
    # every cross-site API response and nobody can stay signed in.
    cookie_samesite = os.environ.get("ALFRED_COOKIE_SAMESITE", "lax").lower()
    cookie_secure = os.environ.get("ALFRED_COOKIE_SECURE", "").lower() in ("1", "true", "yes")

    def _start_session(response: Response, user_id: str) -> None:
        token = secrets.token_urlsafe(32)
        db.create_session(_token_hash(token), user_id, SESSION_TTL_SECONDS)
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=int(SESSION_TTL_SECONDS),
            httponly=True,
            samesite=cookie_samesite,  # type: ignore[arg-type]
            secure=cookie_secure,
        )

    @router.post("/signup")
    def signup(body: dict[str, str], response: Response) -> dict[str, Any]:
        email = (body.get("email") or "").strip()
        password = body.get("password") or ""
        if not _EMAIL_RE.match(email):
            raise HTTPException(status_code=400, detail="enter a valid email address")
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="password must be at least 8 characters")
        if db.get_user_by_email(email):
            raise HTTPException(status_code=409, detail="an account with this email already exists")
        user_id = db.create_user(email, _hash_password(password))
        _start_session(response, user_id)
        return {"user": {"id": user_id, "email": email.lower()}}

    @router.post("/login")
    def login(body: dict[str, str], response: Response) -> dict[str, Any]:
        email = (body.get("email") or "").strip()
        password = body.get("password") or ""
        user = db.get_user_by_email(email)
        if not user or not _verify_password(password, user["password_hash"]):
            # Same message for both cases — do not reveal which emails exist.
            raise HTTPException(status_code=401, detail="invalid email or password")
        _start_session(response, user["id"])
        return {"user": {"id": user["id"], "email": user["email"]}}

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict[str, Any]:
        token = request.cookies.get(COOKIE_NAME, "")
        if token:
            db.delete_session(_token_hash(token))
        response.delete_cookie(COOKIE_NAME)
        return {"ok": True}

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        user = _require_user(request)
        return {"user": user}

    return router
