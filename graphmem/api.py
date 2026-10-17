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
  GET  /admin/db                           -> database caps, graph counts, memory and the slowest queries (read-only)
Admin endpoints are disabled (503) unless GRAPHMEM_ADMIN_KEY is set.
"""
from __future__ import annotations

import collections
import hmac
from urllib.parse import urlparse
import ipaddress
import os
import time
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from pathlib import Path

from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from . import accounts_api, branch, mcp_http, ops, spaces
from .db import Db, Overloaded, QueryLimit
from .dbstats import db_stats
from .textcheck import Clean
from .policy import GraphMem, PermissionDenied


class ShareNew(Clean):
    person: str = Field(max_length=60)
    hours: int = 48
    note: str = Field("", max_length=120)


class ShareReview(Clean):
    name: str = Field(max_length=60)
    note: str = Field("", max_length=300)


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


def client_ip(request: Request) -> str:
    """The caller's address. Behind our own reverse proxy (a private or loopback peer) the proxy puts the real address in X-Forwarded-For; a
    caller that reaches the server directly cannot choose its address that way, because the header is only believed from a private peer."""
    peer = request.client.host if request.client else "?"
    try:
        private = ipaddress.ip_address(peer).is_private
    except ValueError:
        private = False
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or peer if private and fwd else peer


class HourlyCap:
    """At most `limit` events per key in any rolling hour; held in this process's memory like the other limiters."""

    def __init__(self, limit: int):
        self.limit, self.events = limit, {}

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        q = self.events.setdefault(key, collections.deque())
        while q and now - q[0] > 3600:
            q.popleft()
        if len(self.events) > 5000:
            self.events.clear()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


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

    mcp_http.install(app, gm, limiter, bad_auth)             # the MCP server at /mcp, with the same keys and limits

    role = os.getenv("CC_ROLE", "all").lower()   # "all" (default): serve and run the loops; "api": serve only; "worker": run the Telegram/reminder loops (and answer /health)
    background = role in ("all", "worker")

    @app.on_event("startup")
    async def _receipt_secret():              # a wrong secret stops the server here, with the reason, instead of failing every write later
        import asyncio
        from graphmem.care_view import server_secret
        await asyncio.to_thread(server_secret)

    @app.on_event("startup")
    async def _telegram():                    # optional front door: set TELEGRAM_BOT_TOKEN to poll Telegram in this process
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if token and background:
            import asyncio
            from carecircle import telegram
            app.state.tg = asyncio.create_task(telegram.poll(gm, token))

    @app.on_event("startup")
    async def _reminders():                   # the reminder loop does not need Telegram: Web Push alone is enough to start it
        from carecircle import reminders
        if background and reminders.wanted() and os.getenv("CC_REMINDERS", "1") != "0":
            import asyncio
            send = None
            if os.getenv("TELEGRAM_BOT_TOKEN"):
                from carecircle import telegram
                send = telegram._OffLoop(telegram.TgApi(os.environ["TELEGRAM_BOT_TOKEN"])).send
            gm.reminders = reminders.Reminders(gm, send)
            app.state.rem = asyncio.create_task(gm.reminders.run())

    async def agent_id(request: Request, authorization: Optional[str] = Header(None)) -> str:
        ip = client_ip(request)
        token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
        if not token and accounts_api.COOKIE_MODE:                                  # a signed-in browser: the session is in an httpOnly cookie
            token = request.cookies.get(accounts_api.SESSION_COOKIE, "")
            if token and request.method not in ("GET", "HEAD", "OPTIONS"):
                sent, kept = request.headers.get("x-cc-csrf", ""), request.cookies.get(accounts_api.CSRF_COOKIE, "")
                origin = request.headers.get("origin", "")
                same_site = not origin or urlparse(origin).netloc == request.headers.get("host", "")
                if not (sent and kept and hmac.compare_digest(sent, kept) and same_site):
                    raise HTTPException(403, "missing or wrong CSRF token")      # a page on another site cannot send the header or read the cookie
        if not token:
            raise HTTPException(401, "missing bearer token")
        who = await gm.authenticate(token)
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
    demo_circles: list[list] = []                                   # [circle, time it was made]; the time is 0 for those found at startup
    demo_per_caller = HourlyCap(int(os.getenv("CC_DEMO_PER_HOUR", "12")))
    demo_everyone = HourlyCap(int(os.getenv("CC_DEMO_ALL_PER_HOUR", "600")))
    app.state.accounts = accounts_api.mount(app, gm, agent_id, demo_on)            # sign-in, profiles, circles, invitations

    # A read-only link for a pharmacist (carecircle/share.py): the owner makes, lists and revokes; anyone holding the secret may read it until it expires.
    from carecircle.share import Shares, render as render_share
    shares = Shares(gm, app.state.accounts)
    NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}

    @app.post("/v1/circles/{circle}/shares")
    async def share_new(circle: str, b: ShareNew, agent: str = Depends(agent_id)):
        return await shares.create(agent, circle, b.person, b.hours, b.note)

    @app.get("/v1/circles/{circle}/shares")
    async def share_list(circle: str, agent: str = Depends(agent_id)):
        return await shares.list(agent, circle)

    @app.delete("/v1/circles/{circle}/shares/{share_id}")
    async def share_revoke(circle: str, share_id: str, agent: str = Depends(agent_id)):
        return await shares.revoke(agent, circle, share_id)

    @app.get("/v1/share/{token}")
    async def share_json(token: str, request: Request):
        v = await shares.view(token, client_ip(request))
        if v is None:
            raise HTTPException(404, "This link is not open any more.")
        return JSONResponse(v, headers=NO_STORE)

    @app.post("/v1/share/{token}/review")
    async def share_review(token: str, b: ShareReview):
        return JSONResponse(await shares.review(token, b.name, b.note), headers=NO_STORE)

    @app.get("/share/{token}")
    async def share_page(token: str, request: Request):
        v = await shares.view(token, client_ip(request))
        if v is None:
            return HTMLResponse("<!doctype html><meta charset=utf-8><meta name=robots content=noindex><title>Link closed</title><p>This link is not open any more.</p>", status_code=404, headers=NO_STORE)
        return HTMLResponse(render_share(v), headers=NO_STORE)

    @app.post("/demo/start")
    async def demo_start(request: Request):
        """Create a fresh synthetic demo circle (keys returned). Capped: beyond CC_DEMO_MAX the oldest demo circle is deleted, but never one made in the last
        CC_DEMO_KEEP_MIN minutes (someone is probably using it); a caller may make CC_DEMO_PER_HOUR an hour, everyone together CC_DEMO_ALL_PER_HOUR."""
        if not demo_on:
            raise HTTPException(404, "demo disabled")
        if not demo_per_caller.allow(client_ip(request)) or not demo_everyone.allow("all"):
            raise HTTPException(429, "Too many demo circles were started. Wait a little and try again.")
        from carecircle import demo
        cap, keep = int(os.getenv("CC_DEMO_MAX", "40")), float(os.getenv("CC_DEMO_KEEP_MIN", "20")) * 60
        old_enough = lambda e: time.time() - e[1] >= keep  # noqa: E731
        if len(demo_circles) >= 2 * cap and not any(old_enough(e) for e in demo_circles):
            raise HTTPException(503, "The demo is busy right now. Try again in a few minutes.")
        out = await demo.start(gm)
        demo_circles.append([out["circle"], time.time()])
        while len(demo_circles) > cap:
            victim = next((e for e in demo_circles if old_enough(e)), None)
            if victim is None:
                break                                               # everything left is recent: keep it, even if that is briefly over the cap
            demo_circles.remove(victim)
            await demo.forget(gm, victim[0])
        return out

    @app.on_event("startup")
    async def _demo_registry():          # the list above lives in memory: after a restart, take it back from the control graph so the cap still holds
        if not demo_on:
            return
        try:
            from carecircle import demo
            demo_circles[:] = [[c, 0.0] for c in await demo.known(gm)]
            while len(demo_circles) > int(os.getenv("CC_DEMO_MAX", "40")):
                await demo.forget(gm, demo_circles.pop(0)[0])
        except Exception as e:           # never keep the server from starting over housekeeping
            print("demo circle registry not restored:", type(e).__name__, e)

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
        await m._guard("write")                                      # reading a source stores it (so an entry can point at what it was read from)
        from graphmem.care import checker
        if file is not None:
            data = await file.read(ci.MAX_BYTES + 1)
            src = await asyncio.to_thread(ci.read_source, data, file.filename or "", file.content_type or "", language or None)
        else:
            src = ci._done("typed", text, "text")
        if src["status"] != "ok":
            return {"source": {k: src[k] for k in ("kind", "method", "status", "note")}, "text": "", "proposals": []}
        props = await asyncio.to_thread(ci.propose, src["text"], checker())            # the text only: the picture is never sent to a model
        sid = await m.care_store_source(src["kind"], src["text"], src.get("file_sha256", ""), src.get("file_bytes", 0)) if src["kind"] in ("image", "voice", "document") else ""
        return {"source": {k: src[k] for k in ("kind", "method", "status", "note")}, "source_id": sid, "text": src["text"], "proposals": props}

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

    @app.get("/admin/db", dependencies=[Depends(admin)])
    async def database(slowest: int = 10):
        return await db_stats(gm.db, slowest)

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
