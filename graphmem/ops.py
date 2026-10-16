"""The single operation table shared by the HTTP API and the MCP server.

Only names listed here are callable from outside; arguments are bound against the real method signature, so unknown or
missing arguments are rejected before anything touches the graph. Authorization still happens inside TenantMemory on
every query (this module never bypasses it).
"""
from __future__ import annotations

import inspect
from typing import Any

from . import spaces
from .textcheck import check_text
from .memory import TenantMemory
from .policy import GraphMem

OPS = {
    # episodic
    "add_episode": "write", "add_episodes": "write", "assert_facts": "write", "ingest": "write", "history": "read", "sessions": "read", "search_episodes": "read", "search_text": "read",
    # semantic
    "assert_fact": "write", "recall": "read", "fact_history": "read", "embed_missing": "write", "forget_fact": "write",
    # procedural
    "add_skill": "write", "record_run": "write", "best_skills": "read", "skill_runs": "read",
    # coordination
    "create_task": "write", "claim_task": "write", "handoff": "write", "accept": "write", "complete": "write",
    "get_task": "read", "open_tasks": "read", "create_plan": "write", "check_plan": "read", "rebase_plan": "write",
    "resume": "read",
    # traceability
    # graph algorithms on the memory graph
    "graph_schema": "read", "graph_path": "read", "graph_influence": "read", "graph_communities": "read", "graph_neighbourhood": "read",
    # care circle
    "care_record": "write", "care_add_person": "write", "care_timezone": "read", "care_set_timezone": "write", "care_schedule_suggest": "read",
    "care_schedule_set": "write", "care_today": "read", "care_give_slot": "write", "care_slot_nudges": "write", "care_confirm": "write", "care_regimen": "read", "care_duplicates": "read", "care_check": "read", "care_resolve": "read",
    "care_ack": "write", "care_divergence": "read", "care_nudges": "write", "care_reminders": "read", "care_give": "write", "care_gives": "read", "care_people": "read", "care_drug_info": "read", "care_recalls": "read", "care_measure": "write", "care_measures": "read", "care_forget_measure": "write", "care_trend": "read", "care_appoint": "write", "care_appointments": "read", "care_appointment_edit": "write", "care_profile_edit": "write", "care_appointment_cancel": "write", "care_since_visit": "read", "care_condition_add": "write", "care_allergy_add": "write", "care_profile": "read", "care_profile_remove": "write", "care_allergy_check": "read", "care_summary_counts": "read", "care_reading_stats": "read", "care_watch": "write", "care_watched": "read", "care_witness": "write", "care_handover": "write", "care_handovers": "read", "care_sole_knowers": "read", "care_hubs": "read",
    "care_graph": "read", "care_timeline": "read", "care_history_digest": "read", "care_receipt_check": "admin", "care_forget": "admin", "care_forget_person": "admin", "care_mark_mistake": "write", "care_restore_entry": "write", "care_receipts": "read",
    "care_export_fhir": "read",
    "care_followup_suggest": "read", "care_followup_add": "write", "care_followups": "read", "care_followup_done": "write",
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
                     "help": " ".join((inspect.getdoc(fn) or "").split())[:700],          # the whole docstring, for a model that reads tool descriptions
                     "args": [{"name": p.name, "required": p.default is inspect.Parameter.empty} for p in params]}
    return out


SPACE_OPS = {"recall": "read", "fact_history": "read", "stats": "read"}


async def invoke_space(gm: GraphMem, agent: str, space: str, op: str, args: dict[str, Any]) -> Any:
    if op not in SPACE_OPS:
        raise KeyError(f"unknown space operation {op!r}")
    if not isinstance(args, dict):
        raise TypeError("arguments must be an object")
    check_text(args)
    fn = getattr(spaces.open_space(gm, agent, space), op)
    try:
        inspect.signature(fn).bind(**args)
    except TypeError as e:
        raise TypeError(f"{op}: {e}") from None
    return await fn(**args)


MAX_LIMIT = 5000


async def invoke(gm: GraphMem, agent: str, tenant: str, op: str, args: dict[str, Any]) -> Any:
    if op not in OPS:
        raise KeyError(f"unknown operation {op!r}")
    if not isinstance(args, dict):
        raise TypeError("arguments must be an object")
    check_text(args)
    mem = gm.open(agent, tenant)
    if mem._guard:                                  # the scope the table above names is enforced here, once, for every operation: an operation that
        await mem._guard(OPS[op])                   # writes through a path that skips the per-query check (a claim, a delete) cannot be reached with a read-only key
    if op == "forget_fact":  # must also delete copies published to shared spaces
        try:
            inspect.signature(TenantMemory.forget_fact).bind(None, **args)
        except TypeError as e:
            raise TypeError(f"{op}: {e}") from None
        return await spaces.forget_fact(gm, agent, tenant, **args)
    for key in ("limit", "n"):
        if key in args and (isinstance(args[key], bool) or not isinstance(args[key], int) or not 1 <= args[key] <= MAX_LIMIT):
            raise ValueError(f"{key} must be a whole number from 1 to {MAX_LIMIT}")
    fn = getattr(mem, op)
    try:
        inspect.signature(fn).bind(**args)
    except TypeError as e:
        raise TypeError(f"{op}: {e}") from None
    return await fn(**args)
