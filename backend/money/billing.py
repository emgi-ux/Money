"""Subscriptions via Stripe Checkout + Billing Portal.

Modes (``billing_mode()``):
  * ``stripe`` - ``STRIPE_SECRET_KEY`` is set. Real checkout; the webhook at
    /api/billing/webhook keeps plan status in sync. Pro features are paywalled.
  * ``dev``    - ``MONEY_BILLING=dev``. Checkout activates Pro instantly without
    payment, for local testing of the paywall. Never use in production.
  * ``off``    - neither is set. No paywall: every feature is available
    (personal / self-hosted use).

Stripe setup: create a Product with two recurring Prices (weekly and monthly)
and set STRIPE_PRICE_WEEKLY / STRIPE_PRICE_MONTHLY to their IDs, plus
STRIPE_WEBHOOK_SECRET from the webhook endpoint you register.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .db import connect


class BillingError(ValueError):
    pass


def billing_mode() -> str:
    if os.environ.get("STRIPE_SECRET_KEY"):
        return "stripe"
    if os.environ.get("MONEY_BILLING", "").lower() == "dev":
        return "dev"
    return "off"


def paywall_enabled() -> bool:
    return billing_mode() != "off"


def plans() -> list[dict]:
    trial = int(os.environ.get("MONEY_TRIAL_DAYS", "7") or 0)
    return [
        {"id": "weekly", "interval": "week",
         "price": os.environ.get("MONEY_PRICE_WEEKLY_DISPLAY", "$9.99"),
         "price_id": os.environ.get("STRIPE_PRICE_WEEKLY"), "trial_days": trial},
        {"id": "monthly", "interval": "month",
         "price": os.environ.get("MONEY_PRICE_MONTHLY_DISPLAY", "$29.99"),
         "price_id": os.environ.get("STRIPE_PRICE_MONTHLY"), "trial_days": trial,
         "badge": "Best value"},
    ]


def public_plans() -> dict:
    return {
        "mode": billing_mode(),
        "plans": [{k: v for k, v in p.items() if k != "price_id"} for p in plans()],
    }


def _stripe():
    import stripe

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def create_checkout(user: dict, plan_id: str, base_url: str) -> str:
    plan = next((p for p in plans() if p["id"] == plan_id), None)
    if plan is None:
        raise BillingError("Unknown plan")
    mode = billing_mode()
    if mode == "off":
        raise BillingError("Billing is not enabled on this server")
    if mode == "dev":
        _set_plan(user["id"], "pro", plan["interval"], "active",
                  datetime.now(timezone.utc) + timedelta(days=7 if plan["interval"] == "week" else 30))
        return f"{base_url}/#/account?checkout=success"
    if not plan["price_id"]:
        raise BillingError(f"STRIPE_PRICE_{plan_id.upper()} is not configured")

    stripe = _stripe()
    params = {
        "mode": "subscription",
        "line_items": [{"price": plan["price_id"], "quantity": 1}],
        "success_url": f"{base_url}/#/account?checkout=success",
        "cancel_url": f"{base_url}/#/pricing?checkout=cancelled",
        "client_reference_id": str(user["id"]),
        "allow_promotion_codes": True,
        "subscription_data": {"metadata": {"user_id": str(user["id"])}},
    }
    if plan["trial_days"]:
        params["subscription_data"]["trial_period_days"] = plan["trial_days"]
    customer = _customer_id(user["id"])
    if customer:
        params["customer"] = customer
    else:
        params["customer_email"] = user["email"]
    session = stripe.checkout.Session.create(**params)
    return session.url


def create_portal(user: dict, base_url: str) -> str:
    mode = billing_mode()
    if mode == "dev":
        _set_plan(user["id"], "free", None, "canceled", None)
        return f"{base_url}/#/account?portal=cancelled"
    if mode != "stripe":
        raise BillingError("Billing is not enabled on this server")
    customer = _customer_id(user["id"])
    if not customer:
        raise BillingError("No subscription on file")
    session = _stripe().billing_portal.Session.create(customer=customer, return_url=f"{base_url}/#/account")
    return session.url


def handle_webhook(payload: bytes, signature: str | None) -> str:
    """Verify and apply a Stripe webhook event. Returns the event type."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise BillingError("STRIPE_WEBHOOK_SECRET is not configured")
    stripe = _stripe()
    try:
        event = _plain(stripe.Webhook.construct_event(payload, signature or "", secret))
    except Exception as e:  # bad signature or payload
        raise BillingError(f"Invalid webhook: {e}") from e

    with connect() as c:
        if c.execute("SELECT 1 FROM stripe_events WHERE id = ?", (event["id"],)).fetchone():
            return event["type"]  # already processed (Stripe retries)

    obj = event["data"]["object"]
    etype = event["type"]
    if etype == "checkout.session.completed" and obj.get("mode") == "subscription":
        user_id = int(obj["client_reference_id"])
        with connect() as c:
            c.execute("UPDATE users SET stripe_customer_id = ?, stripe_subscription_id = ? WHERE id = ?",
                      (obj["customer"], obj["subscription"], user_id))
        sub = _plain(stripe.Subscription.retrieve(obj["subscription"]))
        _apply_subscription(sub, user_id)
    elif etype in ("customer.subscription.created", "customer.subscription.updated",
                   "customer.subscription.deleted"):
        _apply_subscription(obj)
    # Recorded only after success, so a failed event is retried by Stripe.
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO stripe_events (id) VALUES (?)", (event["id"],))
    return etype


def _plain(obj) -> dict:
    """Stripe SDK objects are not dicts (v13+); work with plain data."""
    return obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)


def _apply_subscription(sub, user_id: int | None = None) -> None:
    if user_id is None:
        meta = sub.get("metadata") or {}
        if meta.get("user_id"):
            user_id = int(meta["user_id"])
        else:
            with connect() as c:
                row = c.execute("SELECT id FROM users WHERE stripe_customer_id = ?",
                                (sub["customer"],)).fetchone()
            if not row:
                return
            user_id = row["id"]
    status = sub["status"]
    items = (sub.get("items") or {}).get("data") or [{}]
    item = items[0]
    interval = ((item.get("price") or {}).get("recurring") or {}).get("interval")
    period_end = sub.get("current_period_end") or item.get("current_period_end")
    renews = datetime.fromtimestamp(period_end, timezone.utc) if period_end else None
    plan = "pro" if status in ("active", "trialing") else "free"
    _set_plan(user_id, plan, interval, status, renews, sub.get("id"), sub.get("customer"))


def _set_plan(user_id: int, plan: str, interval: str | None, status: str | None,
              renews: datetime | None, subscription_id: str | None = None,
              customer_id: str | None = None) -> None:
    with connect() as c:
        c.execute(
            """UPDATE users SET plan = ?, plan_interval = ?, plan_status = ?, plan_renews_at = ?,
                   stripe_subscription_id = COALESCE(?, stripe_subscription_id),
                   stripe_customer_id = COALESCE(?, stripe_customer_id)
               WHERE id = ?""",
            (plan, interval, status, renews.isoformat() if renews else None,
             subscription_id, customer_id, user_id),
        )


def _customer_id(user_id: int) -> str | None:
    with connect() as c:
        row = c.execute("SELECT stripe_customer_id FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["stripe_customer_id"] if row else None


def cancel_subscription_now(user: dict) -> None:
    """Cancel any live Stripe subscription immediately (used on account deletion)."""
    if billing_mode() != "stripe":
        return
    with connect() as c:
        row = c.execute("SELECT stripe_subscription_id FROM users WHERE id = ?", (user["id"],)).fetchone()
    sub_id = row["stripe_subscription_id"] if row else None
    if sub_id:
        try:
            _stripe().Subscription.cancel(sub_id)
        except Exception as e:  # already cancelled / missing: nothing left to bill
            if "No such subscription" not in str(e) and "canceled" not in str(e):
                raise BillingError(f"Could not cancel subscription: {e}") from e
