"""The single operation table shared by the HTTP API and the MCP server.

Only names listed here are callable from outside; arguments are bound against the real method signature, so unknown or
missing arguments are rejected before anything touches the graph. Authorization still happens inside TenantMemory on
every query (this module never bypasses it).
"""
from __future__ import annotations

import inspect
from typing import Any

from . import spaces
from .memory import TenantMemory
from .policy import GraphMem

OPS = {
    # episodic
    "add_episode": "write", "ingest": "write", "history": "read", "sessions": "read", "search_episodes": "read", "search_text": "read",
    # semantic
    "assert_fact": "write", "recall": "read", "fact_history": "read", "embed_missing": "write", "forget_fact": "write",
    # procedural
    "add_skill": "write", "record_run": "write", "best_skills": "read", "skill_runs": "read",
    # coordination
    "create_task": "write", "claim_task": "write", "handoff": "write", "accept": "write", "complete": "write",
    "get_task": "read", "open_tasks": "read", "create_plan": "write", "check_plan": "read", "rebase_plan": "write",
    "resume": "read",
    # traceability
    # care circle
    "care_record": "write", "care_confirm": "write", "care_regimen": "read", "care_check": "read", "care_resolve": "read",
    "care_ack": "write", "care_divergence": "read", "care_nudges": "write", "care_reminders": "read", "care_give": "write", "care_gives": "read", "care_people": "read", "care_drug_info": "read", "care_recalls": "read", "care_measure": "write", "care_measures": "read", "care_forget_measure": "write", "care_trend": "read", "care_appoint": "write", "care_appointments": "read", "care_appointment_cancel": "write", "care_since_visit": "read", "care_condition_add": "write", "care_allergy_add": "write", "care_profile": "read", "care_profile_remove": "write", "care_allergy_check": "read", "care_summary_counts": "read", "care_reading_stats": "read", "care_watch": "write", "care_watched": "read", "care_witness": "write", "care_handover": "write", "care_handovers": "read", "care_sole_knowers": "read", "care_hubs": "read",
    "care_graph": "read", "care_timeline": "read", "care_forget": "write", "care_forget_person": "write", "care_receipts": "read",
    "care_export_fhir": "read",
    "care_chat_ask": "write", "care_chat_history": "read", "care_chat_clear": "write",
    # memory
    "record_decision": "write", "explain": "read", "stats": "read", "graph_view": "read",
}


def describe() -> dict[str, dict]:
    out = {}
    for name, scope in OPS.items():
        fn = getattr(TenantMemory, name)
        params = [p for p in inspect.signature(fn).parameters.values() if p.name != "self"]
        out[name] = {"scope": scope, "doc": (inspect.getdoc(fn) or "").split("\n")[0],
                     "args": [{"name": p.name, "required": p.default is inspect.Parameter.empty} for p in params]}
    return out


SPACE_OPS = {"recall": "read", "fact_history": "read", "stats": "read"}


async def invoke_space(gm: GraphMem, agent: str, space: str, op: str, args: dict[str, Any]) -> Any:
    if op not in SPACE_OPS:
        raise KeyError(f"unknown space operation {op!r}")
    if not isinstance(args, dict):
        raise TypeError("arguments must be an object")
    fn = getattr(spaces.open_space(gm, agent, space), op)
    try:
        inspect.signature(fn).bind(**args)
    except TypeError as e:
        raise TypeError(f"{op}: {e}") from None
    return await fn(**args)


async def invoke(gm: GraphMem, agent: str, tenant: str, op: str, args: dict[str, Any]) -> Any:
    if op not in OPS:
        raise KeyError(f"unknown operation {op!r}")
    if not isinstance(args, dict):
        raise TypeError("arguments must be an object")
    if op == "forget_fact":  # must also delete copies published to shared spaces
        try:
            inspect.signature(TenantMemory.forget_fact).bind(None, **args)
        except TypeError as e:
            raise TypeError(f"{op}: {e}") from None
        return await spaces.forget_fact(gm, agent, tenant, **args)
    fn = getattr(gm.open(agent, tenant), op)
    try:
        inspect.signature(fn).bind(**args)
    except TypeError as e:
        raise TypeError(f"{op}: {e}") from None
    return await fn(**args)
