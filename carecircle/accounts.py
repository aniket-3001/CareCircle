"""Accounts, profiles, circles and invitations, kept in the control graph next to agents and grants.

 (:Account {id, agent, email, name, hash, salt, provider, sub, demo, created_at, tg_code, tg_exp})
 (:Session {hash, exp, at})-[:OF]->(:Account)                          a signed-in browser or phone; only the SHA-256 of its token is stored
 (:Account)-[:MEMBER {role, at}]->(:Tenant {id, name, person, owner})  a circle; `role` is owner or carer
 (:Agent {id})-[:GRANTED {scopes}]->(:Tenant)                          the engine's own access check, written alongside membership
 (:Invite {hash, circle, role, by, exp})                               a one-time code to join a circle
 (:Throttle {key, n, exp})                                             sign-in and assistant limits

An account's agent id is `<firstname>-<6 hex>`, so the engine's per-agent identity, the carer's display name and the audit trail all stay as before.
Two providers: `local` (email and password here, scrypt-hashed) and `cognito` (Amazon Cognito proves the email, we verify its token and keep the
account here). Everything a person sees about their account is read from these nodes; the browser holds only a session token.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Optional

from graphmem.db import now_ms
from graphmem.policy import GraphMem, PermissionDenied

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
SESSION_DAYS = 30
INVITE_HOURS = 72
TG_CODE_MINUTES = 15
DEMO_PASSWORD = "carecircle-demo1"
DEMO_ACCOUNTS = (("ravi@demo.carecircle.app", "Ravi"), ("meena@demo.carecircle.app", "Meena"))
SHARED_CIRCLE = "demo-shared"


def in_quiet(quiet_from: Optional[int], quiet_to: Optional[int], tz_min: int, now: int) -> bool:
    """Is it inside this person's quiet hours? `tz_min` is their offset from UTC in minutes (India: 330). A window like 22 to 7 runs through midnight."""
    if quiet_from is None or quiet_to is None or quiet_from == quiet_to:
        return False
    hour = ((now // 60_000 + tz_min) % 1440) // 60
    return quiet_from <= hour < quiet_to if quiet_from < quiet_to else hour >= quiet_from or hour < quiet_to


class AuthProblem(Exception):
    """A failure with words a person can act on. `status` is the HTTP status to send."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def password_problem(pw: str) -> Optional[str]:
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "The password needs at least 8 characters, with a letter and a number."
    if len(pw) > 128:
        return "That password is too long."
    return None


def _hash(pw: str, salt: bytes) -> str:
    return hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()


def _slug(name: str) -> str:
    first = (name.strip().split() or ["user"])[0].lower()
    return re.sub(r"[^a-z0-9]", "", first)[:12] or "user"


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Accounts:
    def __init__(self, gm: GraphMem):
        self.gm = gm

    async def _g(self):
        return await self.gm._ctl()

    async def _q(self, cypher: str, params: Optional[dict] = None) -> list:
        return (await (await self._g()).query(cypher, params or {})).result_set

    # ------------------------------------------------------------------ limits
    async def hit(self, key: str, limit: int, window_s: int) -> bool:
        """Count one use of `key`; False once `limit` uses have happened in the window. One conditional write, so racing callers cannot both pass."""
        now = int(time.time())
        rows = await self._q(
            """MERGE (t:Throttle {key:$k})
               ON CREATE SET t.n = 0, t.exp = $e
               WITH t, CASE WHEN t.exp < $now THEN 0 ELSE t.n END AS n
               SET t.n = n + 1, t.exp = CASE WHEN t.exp < $now THEN $e ELSE t.exp END
               RETURN t.n""", {"k": key, "e": now + window_s, "now": now})
        return rows[0][0] <= limit

    # ------------------------------------------------------------------ accounts
    def public(self, row: dict) -> dict:
        return {"id": row["agent"], "email": row["email"], "name": row["name"], "provider": row["provider"],
                "demo": bool(row.get("demo")), "created_at": row["created_at"]}

    async def _row(self, where: str, params: dict) -> Optional[dict]:
        r = await self._q(f"MATCH (a:Account) WHERE {where} RETURN a LIMIT 1", params)
        return dict(r[0][0].properties) if r else None

    async def by_email(self, email: str) -> Optional[dict]:
        return await self._row("a.email = $e", {"e": email.strip().lower()})

    async def by_agent(self, agent: str) -> Optional[dict]:
        return await self._row("a.agent = $a", {"a": agent})

    async def create(self, email: str, name: str, password: Optional[str], provider: str = "local", sub: str = "", demo: bool = False) -> dict:
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise AuthProblem("That does not look like an email address.")
        name = " ".join(name.split())[:60] or email.split("@")[0].title()
        if await self.by_email(email):
            raise AuthProblem("There is already an account with that email. Sign in instead.", 409)
        agent = f"{_slug(name)}-{secrets.token_hex(3)}"
        salt = secrets.token_bytes(16)
        pw_hash = _hash(password, salt) if password else ""
        await self.gm.register_agent(agent)
        await self._q("CREATE (:Account {agent:$ag, email:$e, name:$n, hash:$h, salt:$s, provider:$p, sub:$sub, demo:$d, created_at:$t})",
                      {"ag": agent, "e": email, "n": name, "h": pw_hash, "s": salt.hex(), "p": provider, "sub": sub, "d": demo, "t": now_ms()})
        return await self.by_agent(agent)  # type: ignore[return-value]

    async def signup_local(self, email: str, password: str, name: str) -> dict:
        problem = password_problem(password)
        if problem:
            raise AuthProblem(problem)
        if not await self.hit(f"signup|{email.strip().lower()}", 5, 3600):
            raise AuthProblem("Too many tries. Wait a little and try again.", 429)
        return await self.create(email, name, password)

    async def verify_password(self, email: str, password: str) -> dict:
        email = email.strip().lower()
        if not await self.hit(f"signin|{email}", 10, 900):
            raise AuthProblem("Too many tries. Wait a few minutes and try again.", 429)
        row = await self.by_email(email)
        # the same answer and about the same work whether or not the email exists, so the form does not reveal who has an account
        salt = bytes.fromhex(row["salt"]) if row and row.get("salt") else b"\0" * 16
        got = _hash(password, salt)
        if not row or not row.get("hash") or not hmac.compare_digest(got, row["hash"]):
            raise AuthProblem("That email and password do not match.", 401)
        return row

    async def upsert_cognito(self, email: str, sub: str, name: str = "") -> dict:
        row = await self.by_email(email)
        if row:
            if row.get("sub") and row["sub"] != sub:
                raise AuthProblem("That email belongs to a different sign-in.", 409)
            if not row.get("sub"):
                await self._q("MATCH (a:Account {agent:$ag}) SET a.sub=$s, a.provider='cognito'", {"ag": row["agent"], "s": sub})
            return row
        return await self.create(email, name or email.split("@")[0].title(), None, provider="cognito", sub=sub)

    async def update(self, agent: str, name: str) -> dict:
        name = " ".join(name.split())[:60]
        if not name:
            raise AuthProblem("A name cannot be empty.")
        await self._q("MATCH (a:Account {agent:$ag}) SET a.name=$n", {"ag": agent, "n": name})
        return await self.by_agent(agent)  # type: ignore[return-value]

    async def quiet_hours(self, agent: str) -> dict:
        rows = await self._q("MATCH (a:Account {agent:$ag}) RETURN a.quiet_from, a.quiet_to, a.tz", {"ag": agent})
        r = rows[0] if rows else (None, None, 0)
        return {"from": r[0], "to": r[1], "tz": int(r[2] or 0)}

    async def set_quiet_hours(self, agent: str, start: Optional[int], end: Optional[int], tz: int) -> dict:
        """Hours (0 to 23) during which reminders are held back, not dropped: they go out when the window ends. Both None turns it off."""
        if (start is None) != (end is None):
            raise AuthProblem("Give both a start and an end hour, or neither.")
        for h in (start, end):
            if h is not None and not 0 <= h <= 23:
                raise AuthProblem("Hours are 0 to 23.")
        if not -840 <= tz <= 840:
            raise AuthProblem("That time zone is not valid.")
        await self._q("MATCH (a:Account {agent:$ag}) SET a.quiet_from=$f, a.quiet_to=$t, a.tz=$z", {"ag": agent, "f": start, "t": end, "z": int(tz)})
        return await self.quiet_hours(agent)

    async def quiet_now(self, now: int) -> set[str]:
        """Accounts (lower-case agent ids) that are inside their quiet hours at `now`."""
        rows = await self._q("MATCH (a:Account) WHERE a.quiet_from IS NOT NULL RETURN a.agent, a.quiet_from, a.quiet_to, a.tz")
        return {r[0].lower() for r in rows if in_quiet(r[1], r[2], int(r[3] or 0), now)}

    async def change_password(self, agent: str, old: str, new: str, keep_token: str = "") -> None:
        row = await self.by_agent(agent)
        if not row or row["provider"] != "local":
            raise AuthProblem("This account signs in with Amazon Cognito: change the password from the sign-in page ('Forgot your password?').")
        if not row.get("hash") or not hmac.compare_digest(_hash(old, bytes.fromhex(row["salt"])), row["hash"]):
            raise AuthProblem("The current password is not right.", 401)
        problem = password_problem(new)
        if problem:
            raise AuthProblem(problem)
        salt = secrets.token_bytes(16)
        await self._q("MATCH (a:Account {agent:$ag}) SET a.hash=$h, a.salt=$s", {"ag": agent, "h": _hash(new, salt), "s": salt.hex()})
        await self._q("MATCH (a:Account {agent:$ag})<-[:OF]-(s:Session) WHERE s.hash <> $keep DETACH DELETE s", {"ag": agent, "keep": _sha(keep_token) if keep_token else ""})   # every other device signs in again; this one stays

    # ------------------------------------------------------------------ sessions
    async def new_session(self, agent: str) -> str:
        token = "cs_" + secrets.token_urlsafe(32)
        await self._q("MATCH (a:Account {agent:$ag}) CREATE (:Session {hash:$h, at:$t, exp:$e})-[:OF]->(a)",
                      {"ag": agent, "h": _sha(token), "t": now_ms(), "e": now_ms() + SESSION_DAYS * 86_400_000})
        return token

    async def end_session(self, token: str) -> None:
        await self._q("MATCH (s:Session {hash:$h}) DETACH DELETE s", {"h": _sha(token)})

    async def agent_for_session(self, token: str) -> Optional[str]:
        if not token.startswith("cs_") or len(token) > 200:
            return None
        r = await self._q("MATCH (s:Session {hash:$h})-[:OF]->(a:Account) WHERE s.exp > $now RETURN a.agent", {"h": _sha(token), "now": now_ms()})
        return r[0][0] if r else None

    # ------------------------------------------------------------------ circles
    async def circles(self, agent: str) -> list[dict]:
        rows = await self._q(
            """MATCH (:Account {agent:$ag})-[m:MEMBER]->(t:Tenant)
               OPTIONAL MATCH (:Account)-[:MEMBER]->(t)
               WITH t, m, count(*) AS n RETURN t.id, t.name, t.person, m.role, n, t.demo ORDER BY m.at""", {"ag": agent})
        return [{"id": r[0], "name": r[1] or r[0], "person": r[2] or "", "role": r[3], "members": r[4], "demo": bool(r[5])} for r in rows]

    async def create_circle(self, agent: str, name: str, person: str) -> dict:
        name, person = " ".join(name.split())[:60], " ".join(person.split())[:40].lower()
        if not name or not person:
            raise AuthProblem("A circle needs a name and the name of the person it looks after.")
        if len(await self.circles(agent)) >= 10:
            raise AuthProblem("You can be in up to 10 circles.")
        cid = f"c-{_slug(person)}-{secrets.token_hex(3)}"
        await self.gm.create_tenant(cid)
        await self.gm.grant(agent, cid, ("read", "write", "admin"))
        await self._q("""MATCH (a:Account {agent:$ag}), (t:Tenant {id:$c})
                         SET t.name=$n, t.person=$p, t.owner=$ag
                         CREATE (a)-[:MEMBER {role:'owner', at:$t}]->(t)""", {"ag": agent, "c": cid, "n": name, "p": person, "t": now_ms()})
        mem = self.gm.open(agent, cid)
        await mem._q("MERGE (p:Person {id:$p}) ON CREATE SET p.role='patient'", {"p": person})
        await self._register_carer(agent, cid)
        return next(c for c in await self.circles(agent) if c["id"] == cid)

    async def _register_carer(self, agent: str, circle: str) -> None:
        """A member of the circle is a carer from the moment they join, so "who has not seen this" counts them before they have done anything."""
        await self.gm.open(agent, circle)._q("MERGE (c:Person {id:$a}) ON CREATE SET c.role='carer'", {"a": agent.lower()})

    async def role(self, agent: str, circle: str) -> Optional[str]:
        r = await self._q("MATCH (:Account {agent:$ag})-[m:MEMBER]->(:Tenant {id:$c}) RETURN m.role", {"ag": agent, "c": circle})
        return r[0][0] if r else None

    async def members(self, agent: str, circle: str) -> list[dict]:
        if not await self.role(agent, circle):
            raise PermissionDenied("not a member of this circle")
        rows = await self._q("MATCH (a:Account)-[m:MEMBER]->(:Tenant {id:$c}) RETURN a.agent, a.name, m.role, m.at ORDER BY m.at", {"c": circle})
        return [{"id": r[0], "name": r[1], "role": r[2], "since": r[3], "you": r[0] == agent} for r in rows]

    async def rename_circle(self, agent: str, circle: str, name: str) -> None:
        if await self.role(agent, circle) != "owner":
            raise PermissionDenied("only the owner can rename a circle")
        name = " ".join(name.split())[:60]
        if not name:
            raise AuthProblem("A circle needs a name.")
        await self._q("MATCH (t:Tenant {id:$c}) SET t.name=$n", {"c": circle, "n": name})

    async def invite(self, agent: str, circle: str) -> dict:
        if await self.role(agent, circle) != "owner":
            raise PermissionDenied("only the owner can invite carers")
        if not await self.hit(f"invite|{agent}", 20, 3600):
            raise AuthProblem("Too many invitations. Wait a little.", 429)
        alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        exp = now_ms() + INVITE_HOURS * 3_600_000
        await self._q("CREATE (:Invite {hash:$h, circle:$c, by:$ag, exp:$e})", {"h": _sha(code), "c": circle, "ag": agent, "e": exp})
        return {"code": f"{code[:4]}-{code[4:]}", "expires_at": exp, "hours": INVITE_HOURS}

    async def join(self, agent: str, code: str) -> dict:
        code = re.sub(r"[^A-Za-z0-9]", "", code).upper()
        if not await self.hit(f"join|{agent}", 10, 900):
            raise AuthProblem("Too many tries. Wait a few minutes.", 429)
        peek = await self._q("MATCH (i:Invite {hash:$h}) WHERE i.exp > $now RETURN i.circle", {"h": _sha(code), "now": now_ms()})
        if peek and await self.role(agent, peek[0][0]):          # already in: say so, and leave the code unused for the person it was meant for
            raise AuthProblem("You are already in this circle.", 409)
        r = await self._q("MATCH (i:Invite {hash:$h}) WHERE i.exp > $now WITH i, i.circle AS c DETACH DELETE i RETURN c", {"h": _sha(code), "now": now_ms()})
        if not r:
            raise AuthProblem("That code is not valid, or it has expired or been used.", 404)
        cid = r[0][0]
        if not await self.role(agent, cid):
            await self.gm.grant(agent, cid, ("read", "write"))
            await self._q("MATCH (a:Account {agent:$ag}), (t:Tenant {id:$c}) CREATE (a)-[:MEMBER {role:'carer', at:$t}]->(t)", {"ag": agent, "c": cid, "t": now_ms()})
            await self._register_carer(agent, cid)
        return next(c for c in await self.circles(agent) if c["id"] == cid)

    async def leave(self, agent: str, circle: str, target: Optional[str] = None) -> dict:
        """A member leaves, or the owner removes someone. The last owner leaving deletes the circle; with other carers still in it, ownership passes to the longest-standing one."""
        who = target or agent
        mine = await self.role(agent, circle)
        if not mine or (target and target != agent and mine != "owner"):
            raise PermissionDenied("not allowed")
        theirs = await self.role(who, circle)
        if not theirs:
            raise AuthProblem("They are not in this circle.", 404)
        try:                                              # what they said to the assistant goes with them
            g = await self.gm.db.tenant_graph(circle)
            await g.query("MATCH (m:ChatMsg {by:$who}) DELETE m", {"who": who.lower()})
            await g.query("MATCH (p:Person {id:$who, role:'carer'}) DETACH DELETE p", {"who": who.lower()})     # no longer counted as behind
        except Exception:
            pass
        await self.gm.revoke(who, circle)
        await self._q("MATCH (:Account {agent:$ag})-[m:MEMBER]->(:Tenant {id:$c}) DELETE m", {"ag": who, "c": circle})
        await self._q("MATCH (c:TgChat {circle:$c, agent:$ag}) DELETE c", {"c": circle, "ag": who})
        left = await self._q("MATCH (a:Account)-[m:MEMBER]->(:Tenant {id:$c}) RETURN a.agent ORDER BY m.at", {"c": circle})
        if not left:
            await self.gm.db.drop_tenant(circle)
            await self._q("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": circle})
            return {"deleted_circle": True}
        if theirs == "owner":
            nxt = left[0][0]
            await self._q("MATCH (a:Account {agent:$ag})-[m:MEMBER]->(t:Tenant {id:$c}) SET m.role='owner', t.owner=$ag", {"ag": nxt, "c": circle})
            await self.gm.grant(nxt, circle, ("read", "write", "admin"))
        return {"deleted_circle": False}

    async def delete_circle(self, agent: str, circle: str, confirm: str) -> dict:
        """The owner removes a whole circle and everything in it (records, chat, invitations). Typing the circle's name guards against a slip."""
        if await self.role(agent, circle) != "owner":
            raise PermissionDenied("only the owner can delete a circle")
        rows = await self._q("MATCH (t:Tenant {id:$c}) RETURN t.name, t.demo", {"c": circle})
        if not rows:
            raise AuthProblem("No such circle.", 404)
        if rows[0][1]:
            raise AuthProblem("The demo circle is shared and cannot be deleted.", 403)
        if " ".join(confirm.split()).lower() != " ".join((rows[0][0] or circle).split()).lower():
            raise AuthProblem("Type the circle's name to confirm.")
        await self.gm.db.drop_tenant(circle)
        await self._q("MATCH (c:TgChat {circle:$c}) DELETE c", {"c": circle})
        await self._q("MATCH (i:Invite {circle:$c}) DELETE i", {"c": circle})
        await self._q("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": circle})
        return {"deleted_circle": True}

    async def sign_out_everywhere(self, agent: str) -> dict:
        """End every session of this account, on every device (the one making the request included)."""
        rows = await self._q("MATCH (a:Account {agent:$ag})<-[:OF]-(s:Session) WITH s, s AS x DETACH DELETE s RETURN count(x)", {"ag": agent})
        return {"signed_out": int(rows[0][0]) if rows else 0}

    async def export_account(self, agent: str) -> dict:
        """Everything held for this account in one JSON document: profile, and for each circle the record, readings, appointments, notes and follow-ups."""
        row = await self.by_agent(agent)
        if not row:
            raise AuthProblem("No such account.", 404)
        out = {"exported_at": int(time.time() * 1000), "account": self.public(row), "circles": []}
        for c in await self.circles(agent):
            tm, p = self.gm.open(agent, c["id"]), c["person"]
            item = {"circle": c}
            for key, call in (("regimen", tm.care_regimen(p)), ("timeline", tm.care_timeline(p, limit=2000)), ("doses_given", tm.care_gives(p, limit=2000)),
                              ("readings", tm.care_measures(p)), ("appointments", tm.care_appointments(p)), ("profile", tm.care_profile(p)),
                              ("handover_notes", tm.care_handovers(p, limit=2000)), ("follow_ups", tm.care_followups(p)), ("receipts", tm.care_receipts())):
                try:
                    item[key] = await call
                except Exception as e:                      # one part failing must not hide the rest
                    item[key] = {"error": type(e).__name__}
            out["circles"].append(item)
        return out

    async def delete_account(self, agent: str, confirm: str) -> dict:
        row = await self.by_agent(agent)
        if not row:
            raise AuthProblem("No such account.", 404)
        if confirm.strip().lower() != row["email"]:
            raise AuthProblem("Type your email address to confirm.")
        gone = 0
        for c in await self.circles(agent):
            gone += bool((await self.leave(agent, c["id"]))["deleted_circle"])
        await self._q("MATCH (a:Account {agent:$ag}) OPTIONAL MATCH (a)<-[:OF]-(s:Session) DETACH DELETE s, a", {"ag": agent})
        await self._q("MATCH (a:Agent {id:$ag}) OPTIONAL MATCH (a)-[:HAS_KEY]->(k) DETACH DELETE k, a", {"ag": agent})
        await self._q("MATCH (c:TgChat {agent:$ag}) DELETE c", {"ag": agent})
        return {"deleted": True, "circles_deleted": gone}

    # ------------------------------------------------------------------ Telegram link code
    async def telegram_code(self, agent: str) -> dict:
        code = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6))
        exp = int(time.time()) + TG_CODE_MINUTES * 60
        await self._q("MATCH (a:Account {agent:$ag}) SET a.tg_code=$h, a.tg_exp=$e", {"ag": agent, "h": _sha(code), "e": exp})
        return {"code": code, "minutes": TG_CODE_MINUTES}

    async def redeem_telegram_code(self, code: str) -> Optional[str]:
        code = re.sub(r"[^A-Za-z0-9]", "", code).upper()
        r = await self._q("MATCH (a:Account {tg_code:$h}) WHERE a.tg_exp > $now SET a.tg_code = null RETURN a.agent", {"h": _sha(code), "now": int(time.time())})
        return r[0][0] if r else None

    async def telegram_links(self, agent: str) -> list[dict]:
        rows = await self._q("MATCH (c:TgChat {agent:$ag}) RETURN c.chat, c.circle", {"ag": agent})
        return [{"chat": r[0], "circle": r[1]} for r in rows]

    async def unlink_telegram(self, agent: str) -> None:
        await self._q("MATCH (c:TgChat {agent:$ag}) DELETE c", {"ag": agent})
