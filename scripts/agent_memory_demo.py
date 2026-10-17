"""Handoffs without the hand-wringing: one agent writes a note at night, a different agent with its own key starts a fresh session in the morning and finds it
with the path to the entry, and holds off acting until the carer it affects has seen the change.

  python scripts/agent_memory_demo.py --url http://localhost:8099 --admin-key ADMIN        (a server you may write to; it makes a throwaway demo circle)

The two agents are separate MCP clients with their own API keys (made with the admin key and granted read+write on that one circle). They share nothing but the
circle's memory. The same story runs in the test suite (`tests/test_agent_memory_demo.py`) against the engine directly.

What it shows, step by step:
  1. Ravi records warfarin 5 mg and Meena has seen it. At night, Ravi's night agent records the change to 3 mg and writes a NOTE about that entry ("noted by
     night-agent, unverified"): why it changed. The note is not part of the record: it changes no dose, flag or history line.
  2. In the morning a different agent, in a NEW session, asks what it knows about warfarin. Recall returns the note WITH THE PATH to the entry it is about.
     The same question with notes switched off finds nothing: that is the difference the memory makes.
  3. Before acting it checks who has not seen the change. Meena has not, so it HOLDS OFF (it does not write the morning handover) and says who must see it first.
  4. Meena acknowledges the change. The agent checks again, now proceeds, and attaches its handover note to the entry. The entry now shows both notes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Awaitable, Callable

P = "asha"


class LocalAgent:
    """An agent talking to the engine in-process (for tests): the same operations, the same grants and scopes."""

    def __init__(self, gm, agent: str, tenant: str):
        self.gm, self.name, self.tenant = gm, agent, tenant

    async def op(self, name: str, **args) -> Any:
        from graphmem import ops
        return await ops.invoke(self.gm, self.name, self.tenant, name, args)

    async def remember(self, session: str, role: str, content: str, about: str = "") -> Any:
        return await self.op("add_episode", session=session, role=role, content=content, **({"about": about} if about else {}))

    async def recall(self, query: str) -> Any:
        return await self.op("recall", query=query)


class McpAgent:
    """An agent that is a real MCP client with its own key: it uses the `remember`, `recall` and `call` tools of the server's /mcp endpoint, nothing else."""

    def __init__(self, url: str, key: str, tenant: str, name: str):
        self.url, self.key, self.tenant, self.name = url.rstrip("/"), key, tenant, name

    async def _tool(self, tool: str, args: dict) -> Any:
        from mcp import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
        http = create_mcp_http_client(headers={"Authorization": "Bearer " + self.key})
        async with streamable_http_client(f"{self.url}/mcp", http_client=http) as streams:          # a new connection and a new session for every call: nothing is held between them
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
        out = json.loads(res.content[0].text)
        if isinstance(out, dict) and "error" in out:
            raise RuntimeError(out["error"])
        return out

    async def op(self, name: str, **args) -> Any:
        return await self._tool("call", {"tenant": self.tenant, "op": name, "args_json": json.dumps(args)})

    async def remember(self, session: str, role: str, content: str, about: str = "") -> Any:
        return await self._tool("remember", {"tenant": self.tenant, "session": session, "role": role, "content": content, **({"about": about} if about else {})})

    async def recall(self, query: str) -> Any:
        return await self._tool("recall", {"tenant": self.tenant, "query": query})


async def story(night, morning, human: Callable[..., Awaitable[Any]], say: Callable[[str], None] = print) -> dict:
    """The whole demo. `night` and `morning` are two separate agents; `human(who, op, **args)` is what the carers do themselves."""
    ev: dict = {}
    say("1. THE NIGHT")
    await human("ravi", "care_record", person=P, drug="warfarin", dose_text="5 mg", freq_text="at bedtime")
    first = (await human("ravi", "care_regimen", person=P))
    old = next(r for r in first if r["drug"] == "warfarin")
    await human("meena", "care_ack", dose_id=old["id"])
    say(f"   Ravi recorded warfarin 5 mg at bedtime; Meena has seen it.")
    changed = await night.op("care_record", person=P, drug="warfarin", dose_text="3 mg", freq_text="at bedtime")
    entry = changed["id"]
    note = await night.remember("night-1", "agent", "Clinic call 21:40: INR 2.4, dose lowered from 5 mg to 3 mg from tonight. Next INR check Monday.", about=entry)
    say(f"   {night.name} (session night-1) recorded the change to 3 mg and wrote a note about that entry: \"{note['label']}\".")
    await human("ravi", "care_ack", dose_id=entry)
    say("   Ravi asked for the change, so he has seen it. Meena is asleep: she has not.")
    ev.update(entry=entry, note=note)

    say("2. THE MORNING: a different agent, a new session, its own key")
    say(f"   {morning.name} asks: what do I know about warfarin?")
    with_notes = [x for x in await morning.recall("warfarin") if x.get("kind") == "note"]
    for n in with_notes:
        say(f"   - {n['label']}: \"{n['text']}\"")
        say(f"     path: {n['path']}")
    without = [x for x in await morning.op("recall", query="warfarin", notes=False) if x.get("kind") == "note"]
    say(f"   Without the memory (notes off) the same question finds {len(without)} notes: it could see THAT warfarin changed, never WHY.")
    ev.update(recalled=with_notes, without=without)

    say("3. BEFORE ACTING: who has not seen the change?")
    held = await _unseen(morning, entry)
    ev["held"] = held
    if held:
        say(f"   {', '.join(held)} has not seen the change to warfarin. {morning.name} HOLDS OFF: no morning handover is written yet.")
    notes_now = await morning.op("care_entry_notes", dose_id=entry)
    ev["notes_while_held"] = [n["kind"] for n in notes_now["notes"]]

    say("4. THE CARER SEES IT")
    await human("meena", "care_ack", dose_id=entry)
    say("   Meena presses \"I have seen this\".")
    still = await _unseen(morning, entry)
    ev["still_held"] = still
    if not still:
        h = await morning.op("care_handover", person=P, text="Morning: warfarin is 3 mg from tonight per the clinic call (night note). Meena has seen the change.", about=entry)
        say(f"   Nobody is behind, so {morning.name} proceeds and attaches its handover note to the entry ({h['id']}).")
    final = await morning.op("care_entry_notes", dose_id=entry)
    ev["final_notes"] = [(n["kind"], n["label"]) for n in final["notes"]]
    say("   The entry now carries: " + "; ".join(f"{n['label']}" for n in final["notes"]) + ".")
    say("   The record itself: warfarin " + next(r["dose_text"] for r in await human("ravi", "care_regimen", person=P) if r["drug"] == "warfarin") + " (unchanged by any note).")
    return ev


async def _unseen(agent, entry: str) -> list[str]:
    """The carers who have not yet acknowledged this entry (by their first name), read from the shared record."""
    div = await agent.op("care_divergence", person=P)
    return sorted(c.split("-")[0].capitalize() for c, d in div["carers"].items() if any(u["dose"] == entry for u in d["unacknowledged"]))


async def main_http(url: str, admin_key: str) -> int:
    import httpx
    url = url.rstrip("/")
    ah = {"Authorization": f"Bearer {admin_key}"}
    async with httpx.AsyncClient(base_url=url, timeout=60) as c:
        d = (await c.post("/demo/start")).json()
        circle, keys = d["circle"], d["keys"]
        agents = {}
        for name in ("night-agent", "morning-agent"):
            unique = f"{name}-{circle[-6:]}"
            k = (await c.post("/admin/agents", json={"agent": unique}, headers=ah)).json()["api_key"]
            await c.post("/admin/grants", json={"agent": unique, "tenant": circle, "scopes": ["read", "write"]}, headers=ah)
            agents[name] = McpAgent(url, k, circle, unique)

        async def human(who: str, op: str, **args):
            r = await c.post(f"/v1/tenants/{circle}/{op}", json=args, headers={"Authorization": f"Bearer {keys[who]}"})
            r.raise_for_status()
            return r.json()["result"]
        print(f"circle {circle}; agents {agents['night-agent'].name} and {agents['morning-agent'].name}; carers Ravi and Meena\n")
        ev = await story(agents["night-agent"], agents["morning-agent"], human)
        ok = bool(ev["recalled"]) and not ev["without"] and ev["held"] == ["Meena"] and not ev["still_held"] and ev["final_notes"][0][0] == "agent_note"
        print("\nRESULT:", "the agent remembered across sessions, found the note with its path, and held off until the carer had seen the change" if ok else "UNEXPECTED: see above")
        return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://localhost:8099")
    ap.add_argument("--admin-key", required=True)
    a = ap.parse_args()
    sys.exit(asyncio.run(main_http(a.url, a.admin_key)))
