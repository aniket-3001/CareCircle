"""HTTP API. Agents authenticate with `Authorization: Bearer gm_...`; the admin plane needs GRAPHMEM_ADMIN_KEY.

  GET  /healthz
  GET  /v1/me                              -> tenants and scopes of the calling agent
  GET  /v1/ops                             -> operation catalogue
  POST /v1/tenants/{tenant}/{op}           -> run one memory operation (JSON body = its arguments)
  POST /v1/spaces/{space}/publish {tenant,fact_ids}   |  POST /v1/spaces/{space}/{recall|fact_history|stats}
  POST /admin/spaces/members {agent,space,scopes}
  POST /admin/agents  {agent}              -> create agent, returns its API key once
  POST /admin/grants  {agent,tenant,scopes}
  DELETE /admin/grants/{agent}/{tenant}
Admin endpoints are disabled (503) unless GRAPHMEM_ADMIN_KEY is set.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from pathlib import Path

from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from . import accounts_api, branch, ops, spaces
from .db import Db, Overloaded, QueryLimit
from .textcheck import Clean
from .policy import GraphMem, PermissionDenied


class AgentBody(Clean):
    agent: str


class GrantBody(Clean):
    agent: str
    tenant: str
    scopes: list[str] = ["read", "write"]


class MemberBody(Clean):
    agent: str
    space: str
    scopes: list[str] = ["read"]


class ForkBody(Clean):
    label: str = ""


class MergeBody(Clean):
    apply: bool = False
    on_conflict: str = "skip"


class PublishBody(Clean):
    tenant: str
    fact_ids: list[str]


def _bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization[7:].strip()


class RateLimiter:
    """Per-caller token bucket held in this process's memory. With several API processes each enforces its own limit,
    so the effective ceiling is limit x processes; put a shared limiter (proxy/CDN) in front for a hard global cap."""

    def __init__(self, per_minute: int):
        self.rate, self.cap, self.state = per_minute / 60.0, float(per_minute), {}

    def allow(self, who: str) -> bool:
        if self.cap <= 0:
            return True
        now = time.monotonic()
        tokens, last = self.state.get(who, (self.cap, now))
        tokens = min(self.cap, tokens + (now - last) * self.rate)
        if len(self.state) > 10000:           # bound memory under key-spraying
            self.state.clear()
        ok = tokens >= 1.0
        self.state[who] = (tokens - 1.0 if ok else tokens, now)
        return ok


def create_app(gm: Optional[GraphMem] = None, admin_key: Optional[str] = None,
               rate_per_minute: Optional[int] = None) -> FastAPI:
    gm = gm or GraphMem(Db(host=os.getenv("FALKORDB_HOST", "localhost"), port=int(os.getenv("FALKORDB_PORT", "6379"))))
    admin_key = admin_key if admin_key is not None else os.getenv("GRAPHMEM_ADMIN_KEY")
    app = FastAPI(title="graphmem", version="0.1")
    limiter = RateLimiter(rate_per_minute if rate_per_minute is not None else int(os.getenv("GRAPHMEM_RATE_PER_MIN", "600")))
    bad_auth = RateLimiter(30)                # unauthenticated attempts per client IP per minute

    @app.on_event("startup")
    async def _telegram():                    # optional front door: set TELEGRAM_BOT_TOKEN to poll Telegram in this process
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if token:
            import asyncio
            from carecircle import telegram
            app.state.tg = asyncio.create_task(telegram.poll(gm, token))

    async def agent_id(request: Request, authorization: Optional[str] = Header(None)) -> str:
        ip = request.client.host if request.client else "?"
        who = await gm.authenticate(_bearer(authorization))
        if not who:
            if not bad_auth.allow(ip):
                raise HTTPException(429, "too many failed attempts")
            raise HTTPException(401, "invalid api key")
        if not limiter.allow(who):
            raise HTTPException(429, "rate limit exceeded")
        return who

    async def admin(authorization: Optional[str] = Header(None)) -> None:
        if not admin_key:
            raise HTTPException(503, "admin plane disabled: set GRAPHMEM_ADMIN_KEY")
        if not hmac.compare_digest(_bearer(authorization), admin_key):
            raise HTTPException(401, "invalid admin key")

    @app.exception_handler(PermissionDenied)
    async def _denied(_: Request, e: PermissionDenied):
        return JSONResponse({"error": str(e)}, status_code=403)

    @app.exception_handler(Overloaded)
    async def _busy(_: Request, e: Overloaded):
        return JSONResponse({"error": str(e)}, status_code=503, headers={"Retry-After": "1"})

    @app.exception_handler(QueryLimit)
    async def _too_heavy(_: Request, e: QueryLimit):
        return JSONResponse({"error": str(e)}, status_code=503)

    @app.exception_handler(KeyError)
    async def _missing(_: Request, e: KeyError):
        return JSONResponse({"error": f"not found: {e.args[0] if e.args else ''}"}, status_code=404)

    @app.exception_handler(ValueError)
    @app.exception_handler(TypeError)
    async def _bad(_: Request, e: Exception):
        return JSONResponse({"error": str(e)}, status_code=422)

    dist = Path(os.getenv("CC_WEB_DIST") or Path(__file__).resolve().parent.parent / "web" / "dist")

    @app.get("/", response_class=HTMLResponse)
    async def ui():
        index = dist / "index.html"
        if not index.exists():
            return HTMLResponse("<h1>Care Circle API</h1><p>The web app is not built: run <code>npm ci && npm run build</code> in <code>web/</code>.</p>", status_code=503)
        return HTMLResponse(index.read_text(encoding="utf-8"), headers={"cache-control": "no-cache"})

    @app.get("/sw.js")
    async def service_worker():
        """The notification service worker must be served from the site root (its scope), and must never be cached by the browser."""
        sw = dist / "sw.js"
        if not sw.exists():
            raise HTTPException(404, "no service worker")
        return Response(sw.read_text(encoding="utf-8"), media_type="text/javascript", headers={"cache-control": "no-cache", "service-worker-allowed": "/"})

    if (dist / "assets").exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")     # hashed file names: cacheable

    demo_on = os.getenv("CC_DEMO", "1") == "1"
    demo_circles: list[str] = []
    app.state.accounts = accounts_api.mount(app, gm, agent_id, demo_on)            # sign-in, profiles, circles, invitations

    @app.post("/demo/start")
    async def demo_start():
        """Create a fresh synthetic demo circle (keys returned). Capped: the oldest demo circle is deleted beyond CC_DEMO_MAX."""
        if not demo_on:
            raise HTTPException(404, "demo disabled")
        from carecircle import demo
        out = await demo.start(gm)
        demo_circles.append(out["circle"])
        while len(demo_circles) > int(os.getenv("CC_DEMO_MAX", "40")):
            await gm.db.drop_tenant(demo_circles.pop(0))
        return out

    @app.get("/demo/label.png")
    async def demo_label(drug: str = "Clarithromycin 500 mg tablets", sig: str = "Take ONE tablet twice daily for 7 days"):
        from fastapi.responses import Response
        from carecircle import demo
        return Response(demo.label_png(drug[:60], sig[:80]), media_type="image/png")

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/v1/me")
    async def me(agent: str = Depends(agent_id)):
        return {"agent": agent, "tenants": await gm.tenants_of(agent), "spaces": await gm.spaces_of(agent)}

    @app.get("/v1/ops")
    async def catalogue(agent: str = Depends(agent_id)):
        return ops.describe()

    @app.exception_handler(branch.ForkError)
    async def _fork_err(_: Request, e: branch.ForkError):
        return JSONResponse({"error": str(e)}, status_code=409)

    @app.post("/v1/tenants/{tenant}/intake")
    async def intake(tenant: str, file: UploadFile = File(None), text: str = Form(""), language: str = Form(""),
                     agent: str = Depends(agent_id)):
        """Photo / voice / PDF / DOCX / text -> proposed medication entries (nothing is written; each needs a person's confirmation)."""
        import asyncio
        from carecircle import intake as ci
        m = gm.open(agent, tenant)
        await m.care_resolve("x")                                    # read-scope check on the tenant
        from graphmem.care import checker
        if file is not None:
            data = await file.read(ci.MAX_BYTES + 1)
            src = await asyncio.to_thread(ci.read_source, data, file.filename or "", file.content_type or "", language or None)
        else:
            src = ci._done("typed", text, "text")
        if src["status"] != "ok":
            return {"source": {k: src[k] for k in ("kind", "method", "status", "note")}, "text": "", "proposals": []}
        img = data if file is not None and src["kind"] == "image" else None
        fmt = (file.filename.rsplit(".", 1)[-1].lower() if img else "png").replace("jpg", "jpeg")
        props = await asyncio.to_thread(ci.propose, src["text"], checker(), img, fmt if fmt in ("png", "jpeg", "webp") else "png")
        return {"source": {k: src[k] for k in ("kind", "method", "status", "note")}, "text": src["text"], "proposals": props}

    @app.post("/v1/tenants/{tenant}/forks")
    async def fork_create(tenant: str, b: ForkBody, agent: str = Depends(agent_id)):
        return {"result": await branch.fork(gm, agent, tenant, b.label)}

    @app.get("/v1/tenants/{tenant}/forks")
    async def fork_list(tenant: str, agent: str = Depends(agent_id)):
        return {"result": await branch.list_forks(gm, agent, tenant)}

    @app.post("/v1/forks/{fork_id}/merge")
    async def fork_merge(fork_id: str, b: MergeBody, agent: str = Depends(agent_id)):
        return {"result": await branch.merge(gm, agent, fork_id, apply=b.apply, on_conflict=b.on_conflict)}

    @app.delete("/v1/forks/{fork_id}")
    async def fork_discard(fork_id: str, agent: str = Depends(agent_id)):
        await branch.discard(gm, agent, fork_id)
        return {"ok": True}

    @app.post("/v1/forks/{fork_id}/{op}")
    async def fork_op(fork_id: str, op: str, request: Request, agent: str = Depends(agent_id)):
        if op not in ops.OPS:
            raise KeyError(f"unknown operation {op!r}")
        body = await request.json() if await request.body() else {}
        fm = await branch.open_fork(gm, agent, fork_id)
        return {"result": await getattr(fm, op)(**body)}

    @app.post("/v1/tenants/{tenant}/{op}")
    async def run(tenant: str, op: str, request: Request, agent: str = Depends(agent_id)):
        try:
            body = await request.json() if await request.body() else {}
        except ValueError:
            raise HTTPException(422, "body must be JSON")
        return {"result": await ops.invoke(gm, agent, tenant, op, body)}

    @app.post("/v1/spaces/{space}/publish")
    async def publish(space: str, b: PublishBody, agent: str = Depends(agent_id)):
        return {"result": await spaces.publish(gm, agent, b.tenant, space, b.fact_ids)}

    @app.post("/v1/spaces/{space}/{op}")
    async def space_run(space: str, op: str, request: Request, agent: str = Depends(agent_id)):
        try:
            body = await request.json() if await request.body() else {}
        except ValueError:
            raise HTTPException(422, "body must be JSON")
        return {"result": await ops.invoke_space(gm, agent, space, op, body)}

    @app.post("/admin/spaces/members", dependencies=[Depends(admin)])
    async def space_member(b: MemberBody):
        await spaces.add_member(gm, b.agent, b.space, tuple(b.scopes))
        return {"ok": True}

    @app.delete("/admin/spaces/{space}/members/{agent}", dependencies=[Depends(admin)])
    async def space_member_del(space: str, agent: str):
        await spaces.remove_member(gm, agent, space)
        return {"ok": True}

    @app.post("/admin/agents", dependencies=[Depends(admin)])
    async def new_agent(b: AgentBody):
        return {"agent": b.agent, "api_key": await gm.issue_key(b.agent)}

    @app.post("/admin/grants", dependencies=[Depends(admin)])
    async def new_grant(b: GrantBody):
        await gm.grant(b.agent, b.tenant, tuple(b.scopes))
        return {"ok": True}

    @app.delete("/admin/grants/{agent}/{tenant}", dependencies=[Depends(admin)])
    async def del_grant(agent: str, tenant: str):
        await gm.revoke(agent, tenant)
        return {"ok": True}

    app.state.gm = gm
    return app


def main() -> None:  # pragma: no cover
    import uvicorn
    uvicorn.run(create_app(), host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":  # pragma: no cover
    main()
