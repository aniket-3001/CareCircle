"""Control plane: tenants, agents and access grants live in the `ctl` graph, and every memory call is authorized by
traversing it:  (Agent)-[:GRANTED {scopes}]->(Tenant).  No grant -> no access to that tenant's graph.

Scopes: 'read' (recall, history, explain), 'write' (everything that mutates), 'admin' (grants, forgetting tenants).
Agents never receive a graph handle for a tenant they hold no grant for; TenantMemory calls the guard on every query.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

from .db import CTL_GRAPH, Db, now_ms, validate_tenant
from .extract import from_env
from .memory import TenantMemory

SCOPES = ("read", "write", "admin")


class PermissionDenied(Exception):
    pass


class GraphMem:
    def __init__(self, db: Db, extractor=None):
        self.db = db
        self.extractor = extractor or from_env()   # None -> rule extractor

    async def _ctl(self):
        return await self.db.graph(CTL_GRAPH)

    # -------------------------------------------------------------- admin
    async def create_tenant(self, tenant: str) -> None:
        validate_tenant(tenant)
        g = await self._ctl()
        await g.query("MERGE (t:Tenant {id:$t}) ON CREATE SET t.created_at=$ts", {"t": tenant, "ts": now_ms()})
        await self.db.tenant_graph(tenant)  # create graph + indexes eagerly

    async def register_agent(self, agent: str) -> None:
        g = await self._ctl()
        await g.query("MERGE (a:Agent {id:$a}) ON CREATE SET a.created_at=$ts", {"a": agent, "ts": now_ms()})

    async def issue_key(self, agent: str) -> str:
        """Create an API key for an agent. The plaintext is returned once; only its SHA-256 is stored."""
        await self.register_agent(agent)
        token = "gm_" + secrets.token_urlsafe(32)
        g = await self._ctl()
        await g.query("MATCH (a:Agent {id:$a}) CREATE (a)-[:HAS_KEY]->(:ApiKey {hash:$h, at:$ts})",
                      {"a": agent, "h": hashlib.sha256(token.encode()).hexdigest(), "ts": now_ms()})
        return token

    async def authenticate(self, token: str) -> Optional[str]:
        """Return the agent id owning this key, or None. Lookup is by hash, never by plaintext."""
        if token and token.startswith("cs_") and len(token) <= 200:           # a signed-in person's session (carecircle/accounts.py)
            g = await self._ctl()
            r = (await g.query("MATCH (s:Session {hash:$h})-[:OF]->(a:Account) WHERE s.exp > $now RETURN a.agent",
                               {"h": hashlib.sha256(token.encode()).hexdigest(), "now": now_ms()})).result_set
            return r[0][0] if r else None
        if not token or not token.startswith("gm_") or len(token) > 200:
            return None
        h = hashlib.sha256(token.encode()).hexdigest()
        g = await self._ctl()
        rows = (await g.query("MATCH (a:Agent)-[:HAS_KEY]->(k:ApiKey {hash:$h}) RETURN a.id, k.hash", {"h": h})).result_set
        return rows[0][0] if rows and hmac.compare_digest(rows[0][1], h) else None

    async def revoke_keys(self, agent: str) -> None:
        g = await self._ctl()
        await g.query("MATCH (:Agent {id:$a})-[:HAS_KEY]->(k:ApiKey) DETACH DELETE k", {"a": agent})

    async def grant(self, agent: str, tenant: str, scopes: tuple[str, ...] = ("read", "write")) -> None:
        bad = set(scopes) - set(SCOPES)
        if bad:
            raise ValueError(f"unknown scopes {bad}")
        await self.create_tenant(tenant)
        g = await self._ctl()
        await g.query(
            "MERGE (a:Agent {id:$a}) MERGE (t:Tenant {id:$t}) MERGE (a)-[g:GRANTED]->(t) SET g.scopes=$s, g.at=$ts",
            {"a": agent, "t": tenant, "s": list(scopes), "ts": now_ms()})

    async def revoke(self, agent: str, tenant: str) -> None:
        g = await self._ctl()
        await g.query("MATCH (:Agent {id:$a})-[g:GRANTED]->(:Tenant {id:$t}) DELETE g", {"a": agent, "t": tenant})

    async def scopes(self, agent: str, tenant: str) -> set[str]:
        g = await self._ctl()
        rows = (await g.query("MATCH (:Agent {id:$a})-[g:GRANTED]->(:Tenant {id:$t}) RETURN g.scopes",
                              {"a": agent, "t": tenant})).result_set
        return set(rows[0][0]) if rows else set()

    async def tenants_of(self, agent: str) -> dict[str, list[str]]:
        g = await self._ctl()
        rows = (await g.query("MATCH (:Agent {id:$a})-[g:GRANTED]->(t:Tenant) RETURN t.id, g.scopes",
                              {"a": agent})).result_set
        return {r[0]: list(r[1]) for r in rows}

    async def spaces_of(self, agent: str) -> dict[str, list[str]]:
        g = await self._ctl()
        rows = (await g.query("MATCH (:Agent {id:$a})-[m:MEMBER]->(s:Space) RETURN s.id, m.scopes", {"a": agent})).result_set
        return {r[0]: list(r[1]) for r in rows}

    # -------------------------------------------------------------- access
    def open(self, agent: str, tenant: str) -> TenantMemory:
        """Return a memory handle for (agent, tenant). Authorization is checked lazily on every query so a revoke
        takes effect immediately, even for handles that were opened earlier."""
        validate_tenant(tenant)

        async def guard(scope: str) -> None:
            have = await self.scopes(agent, tenant)
            ok = scope in have or ("admin" in have)
            if not ok:
                raise PermissionDenied(f"agent {agent!r} lacks {scope!r} on tenant {tenant!r}")

        return TenantMemory(self.db, tenant, agent, guard, extractor=self.extractor)

    async def forget_tenant(self, agent: str, tenant: str) -> None:
        if "admin" not in await self.scopes(agent, tenant):
            raise PermissionDenied(f"agent {agent!r} lacks 'admin' on tenant {tenant!r}")
        await self.db.drop_tenant(tenant)
        g = await self._ctl()
        await g.query("MATCH (t:Tenant {id:$t}) DETACH DELETE t", {"t": tenant})
