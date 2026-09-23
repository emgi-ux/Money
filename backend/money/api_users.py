"""Routes for accounts, subscriptions, paper trading and copy trading."""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import auth, billing, trading
from .data import get_provider
from .db import db_path

router = APIRouter(prefix="/api")


# ------------------------------------------------------------- dependencies
def _token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    return auth.user_for_token(_token(authorization))


def require_user(user: dict | None = Depends(optional_user)) -> dict:
    if not user:
        raise HTTPException(401, "Sign in to continue")
    return user


def require_pro(user: dict | None = Depends(optional_user)) -> dict | None:
    """Gate for Pro features. A no-op when billing is off (self-hosted use)."""
    if not billing.paywall_enabled():
        return user
    if not user:
        raise HTTPException(401, "Sign in to continue")
    if not user["is_pro"]:
        raise HTTPException(402, "This is a Pro feature. Upgrade to unlock it.")
    return user


def _base_url(request: Request) -> str:
    return os.environ.get("MONEY_PUBLIC_URL", str(request.base_url)).rstrip("/")


def _client(request: Request) -> str:
    return request.client.host if request.client else ""


# --------------------------------------------------------------------- auth
class RegisterBody(BaseModel):
    email: str
    password: str
    display_name: str


class LoginBody(BaseModel):
    email: str
    password: str


class ProfileBody(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    is_public: bool | None = None


@router.post("/auth/register")
def register(body: RegisterBody):
    try:
        out = auth.register(body.email, body.password, body.display_name)
    except auth.AuthError as e:
        raise HTTPException(400, str(e)) from e
    trading.ensure_account(out["user"]["id"])
    return out


@router.post("/auth/login")
def login(body: LoginBody, request: Request):
    try:
        return auth.login(body.email, body.password, _client(request))
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from e


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    if tok := _token(authorization):
        auth.logout(tok)
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(require_user)):
    return {"user": user, "billing": billing.public_plans()}


@router.patch("/auth/me")
def update_me(body: ProfileBody, user: dict = Depends(require_user)):
    try:
        return {"user": auth.update_profile(user["id"], body.display_name, body.bio, body.is_public)}
    except auth.AuthError as e:
        raise HTTPException(400, str(e)) from e


class ForgotBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    token: str
    password: str


class DeleteBody(BaseModel):
    password: str


@router.post("/auth/forgot")
def forgot(body: ForgotBody, request: Request):
    try:
        auth.request_password_reset(body.email, _base_url(request))
    except auth.AuthError as e:
        raise HTTPException(429, str(e)) from e
    # Same response whether or not the email exists.
    return {"ok": True}


@router.post("/auth/reset")
def reset_password(body: ResetBody):
    try:
        return auth.reset_password(body.token, body.password)
    except auth.AuthError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/auth/me")
def delete_me(body: DeleteBody, user: dict = Depends(require_user)):
    if not auth.check_password(user["id"], body.password):
        raise HTTPException(403, "Incorrect password")
    try:
        billing.cancel_subscription_now(user)
    except billing.BillingError as e:
        raise HTTPException(502, str(e)) from e
    auth.delete_user(user["id"])
    return {"ok": True}


# ------------------------------------------------------------------ billing
class CheckoutBody(BaseModel):
    plan: str


@router.get("/billing/plans")
def plans():
    return billing.public_plans()


@router.post("/billing/checkout")
def checkout(body: CheckoutBody, request: Request, user: dict = Depends(require_user)):
    try:
        return {"url": billing.create_checkout(user, body.plan, _base_url(request))}
    except billing.BillingError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/billing/portal")
def portal(request: Request, user: dict = Depends(require_user)):
    try:
        return {"url": billing.create_portal(user, _base_url(request))}
    except billing.BillingError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/billing/webhook", include_in_schema=False)
async def webhook(request: Request, stripe_signature: str | None = Header(default=None)):
    try:
        return {"received": billing.handle_webhook(await request.body(), stripe_signature)}
    except billing.BillingError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------ trading
class OrderBody(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    side: str
    qty: float = Field(gt=0)


class CopyBody(BaseModel):
    allocation: float = Field(gt=0)


@router.get("/paper")
def paper(user: dict = Depends(require_user)):
    return trading.portfolio(get_provider(), user["id"])


@router.post("/paper/order")
def order(body: OrderBody, user: dict = Depends(require_user)):
    try:
        return trading.place_order(get_provider(), user["id"], body.ticker, body.side, body.qty)
    except trading.TradeError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/paper/reset")
def reset(user: dict = Depends(require_user)):
    trading.reset_account(user["id"])
    return {"ok": True}


_board_cache: dict[str, tuple[float, list]] = {}
BOARD_TTL = 60


@router.get("/leaderboard")
def leaderboard(sort: str = Query("total_return")):
    # Bots are backfilled in the background at startup; never block a request on it.
    key = f"{db_path()}|{sort}"
    hit = _board_cache.get(key)
    if hit is None or time.time() - hit[0] > BOARD_TTL:
        hit = (time.time(), trading.leaderboard(get_provider(), sort))
        if trading.bots_ready():  # don't cache a half-seeded board
            _board_cache[key] = hit
    return {"rows": hit[1]}


@router.get("/traders/{trader_id}")
def trader(trader_id: int, user: dict | None = Depends(optional_user)):
    try:
        return trading.trader_profile(get_provider(), trader_id, user["id"] if user else None)
    except trading.TradeError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/traders/{trader_id}/copy")
def copy(trader_id: int, body: CopyBody, user: dict = Depends(require_user),
         _: dict | None = Depends(require_pro)):
    try:
        return trading.start_copy(get_provider(), user["id"], trader_id, body.allocation)
    except trading.TradeError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/traders/{trader_id}/copy")
def uncopy(trader_id: int, user: dict = Depends(require_user)):
    trading.stop_copy(user["id"], trader_id)
    return {"ok": True}
