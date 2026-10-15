"""HTTP routes for accounts, profiles, circles and invitations (carecircle/accounts.py). Mounted by api.create_app.

 GET  /v1/auth/config                  which sign-in is on (Cognito or local), and the public demo accounts
 POST /v1/auth/signup | /signin        local email-and-password accounts        (Cognito users sign in at Cognito and use /exchange)
 POST /v1/auth/exchange                a Cognito ID token -> our session
 POST /v1/auth/signout
 GET|PATCH|DELETE /v1/account          the profile; deleting removes the account and every circle only you were in
 POST /v1/account/password             change a local password
 GET|POST /v1/account/circles          your circles; create one
 POST /v1/account/telegram-code        a one-time code to link the Telegram bot;  DELETE /v1/account/telegram unlinks
 GET|PATCH /v1/circles/{id}  members | rename;  POST /v1/circles/{id}/invites;  POST /v1/join;  POST /v1/circles/{id}/leave;  DELETE /v1/circles/{id}/members/{agent}
 POST /v1/demo/reset                   rebuild the shared demo circle (demo accounts only)
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from carecircle import cognito as cog
from carecircle import demo
from carecircle.accounts import DEMO_ACCOUNTS, DEMO_PASSWORD, Accounts, AuthProblem
from .policy import GraphMem, PermissionDenied


class SignUp(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    name: str = Field(default="", max_length=80)


class SignIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class Exchange(BaseModel):
    name: str = Field(default="", max_length=80)


class Profile(BaseModel):
    name: str = Field(max_length=80)


class Password(BaseModel):
    old: str = Field(max_length=200)
    new: str = Field(max_length=200)


class NewCircle(BaseModel):
    name: str = Field(max_length=80)
    person: str = Field(max_length=60)


class Rename(BaseModel):
    name: str = Field(max_length=80)


class Join(BaseModel):
    code: str = Field(max_length=40)


class Delete(BaseModel):
    confirm: str = Field(max_length=254)


def _bearer(h: Optional[str]) -> str:
    return h.split(" ", 1)[1].strip() if h and h.lower().startswith("bearer ") else ""


def mount(app: FastAPI, gm: GraphMem, agent_id, demo_on: bool) -> Accounts:
    acc = Accounts(gm)
    cfg = cog.from_env()

    @app.exception_handler(AuthProblem)
    async def _auth_problem(_: Request, e: AuthProblem):
        return JSONResponse({"error": str(e)}, status_code=e.status)

    async def seed() -> None:
        if demo_on:
            await demo.seed_shared(gm, acc)

    @app.on_event("startup")
    async def _seed_demo_accounts():
        try:
            await seed()
        except Exception as e:                      # never keep the app from starting
            print("demo account seeding failed:", type(e).__name__, e, flush=True)

    async def session_for(row: dict) -> dict:
        return {"token": await acc.new_session(row["agent"]), "account": acc.public(row)}

    # -------------------------------------------------------------- sign-in
    @app.get("/v1/auth/config")
    async def auth_config():
        return {"provider": "cognito" if cfg else "local",
                "cognito": {"region": cfg.region, "userPoolId": cfg.pool_id, "clientId": cfg.client_id} if cfg else None,
                "demo_accounts": [{"email": e, "name": n, "password": DEMO_PASSWORD} for e, n in DEMO_ACCOUNTS] if demo_on else [],
                "password_rule": "At least 8 characters, with a letter and a number."}

    @app.post("/v1/auth/signup")
    async def signup(b: SignUp):
        if cfg:
            raise AuthProblem("Create your account on the sign-up page (Amazon Cognito sends the confirmation code).")
        return await session_for(await acc.signup_local(b.email, b.password, b.name))

    @app.post("/v1/auth/signin")
    async def signin(b: SignIn):
        return await session_for(await acc.verify_password(b.email, b.password))

    @app.post("/v1/auth/exchange")
    async def exchange(b: Exchange, authorization: Optional[str] = Header(None)):
        if not cfg:
            raise AuthProblem("Cognito sign-in is not switched on here.", 404)
        try:
            claims = cog.verify_id_token(_bearer(authorization), cfg)
        except ValueError:
            raise AuthProblem("Your sign-in could not be checked. Sign in again.", 401)
        if not await acc.hit(f"exchange|{claims['sub']}", 30, 900):
            raise AuthProblem("Too many tries. Wait a few minutes.", 429)
        return await session_for(await acc.upsert_cognito(claims["email"], claims["sub"], b.name or claims.get("name", "")))

    @app.post("/v1/auth/signout")
    async def signout(authorization: Optional[str] = Header(None)):
        await acc.end_session(_bearer(authorization))
        return {"ok": True}

    # -------------------------------------------------------------- the account
    async def profile(agent: str) -> dict:
        row = await acc.by_agent(agent)
        if not row:
            raise HTTPException(404, "this key belongs to an agent, not an account")
        return {**acc.public(row), "circles": await acc.circles(agent), "telegram": await acc.telegram_links(agent)}

    @app.get("/v1/account")
    async def get_account(agent: str = Depends(agent_id)):
        return await profile(agent)

    @app.patch("/v1/account")
    async def patch_account(b: Profile, agent: str = Depends(agent_id)):
        await acc.update(agent, b.name)
        return await profile(agent)

    @app.post("/v1/account/password")
    async def password(b: Password, agent: str = Depends(agent_id)):
        await acc.change_password(agent, b.old, b.new)
        return {"ok": True}

    @app.delete("/v1/account")
    async def delete_account(b: Delete, agent: str = Depends(agent_id)):
        row = await acc.by_agent(agent)
        if row and row.get("demo"):
            raise AuthProblem("The demo accounts are shared and cannot be deleted. Create your own account.", 403)
        return await acc.delete_account(agent, b.confirm)

    @app.get("/v1/account/circles")
    async def my_circles(agent: str = Depends(agent_id)):
        return await acc.circles(agent)

    @app.post("/v1/account/circles")
    async def new_circle(b: NewCircle, agent: str = Depends(agent_id)):
        return await acc.create_circle(agent, b.name, b.person)

    @app.post("/v1/account/telegram-code")
    async def tg_code(agent: str = Depends(agent_id)):
        return await acc.telegram_code(agent)

    @app.delete("/v1/account/telegram")
    async def tg_unlink(agent: str = Depends(agent_id)):
        await acc.unlink_telegram(agent)
        return {"ok": True}

    # -------------------------------------------------------------- circles
    @app.get("/v1/circles/{circle}/members")
    async def members(circle: str, agent: str = Depends(agent_id)):
        return await acc.members(agent, circle)

    @app.patch("/v1/circles/{circle}")
    async def rename(circle: str, b: Rename, agent: str = Depends(agent_id)):
        await acc.rename_circle(agent, circle, b.name)
        return {"ok": True}

    @app.post("/v1/circles/{circle}/invites")
    async def invite(circle: str, agent: str = Depends(agent_id)):
        return await acc.invite(agent, circle)

    @app.post("/v1/join")
    async def join(b: Join, agent: str = Depends(agent_id)):
        return await acc.join(agent, b.code)

    @app.post("/v1/circles/{circle}/leave")
    async def leave(circle: str, agent: str = Depends(agent_id)):
        return await acc.leave(agent, circle)

    @app.delete("/v1/circles/{circle}/members/{member}")
    async def remove(circle: str, member: str, agent: str = Depends(agent_id)):
        return await acc.leave(agent, circle, member)

    @app.post("/v1/demo/reset")
    async def reset(agent: str = Depends(agent_id)):
        row = await acc.by_agent(agent)
        if not (demo_on and row and row.get("demo")):
            raise PermissionDenied("only the demo accounts can reset the demo circle")
        await demo.reset_shared(gm, acc)
        return {"ok": True}

    return acc
