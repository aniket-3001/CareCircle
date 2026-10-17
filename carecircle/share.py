"""A read-only link for a pharmacist: the owner makes it, it expires, it can be revoked, and it shows the record and the cross-checks, nothing more.

  (:Share {id, hash, circle, person, by, created, exp, note, views, revoked})      in the control graph. Only a SHA-256 of the link's secret is stored.

What the link shows: the medicines on record with dose, times, product and how each was entered; the interaction flags and possible duplicates with their sources;
recorded allergies that match; the same plain statement the app shows (never "safe"). What it does not show: carers' names, the chat, handover notes, appointments,
the quoted lines or the source text. The viewer can write back a name and a short note; the name is typed, not verified, and the circle sees it labelled that way.
Opening the link needs nothing but the secret, so it is a secret: treat it like a password for as long as it lives.
"""
from __future__ import annotations

import hashlib
import html
import secrets
import time
from typing import Optional

from graphmem.db import new_id, norm, now_ms
from graphmem.policy import GraphMem, PermissionDenied

from .accounts import AuthProblem

MAX_ACTIVE = 3
MIN_H, MAX_H, DEFAULT_H = 1, 168, 48
HOW = {"photo": "photo", "voice": "voice note", "document": "document", "typed": "typed"}


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Shares:
    def __init__(self, gm: GraphMem, accounts):
        self.gm, self.acc = gm, accounts

    async def _q(self, cypher: str, params: Optional[dict] = None) -> list:
        return (await (await self.gm._ctl()).query(cypher, params or {})).result_set

    # ------------------------------------------------------------------ the owner's side
    async def create(self, agent: str, circle: str, person: str, hours: int = DEFAULT_H, note: str = "") -> dict:
        if await self.acc.role(agent, circle) != "owner":
            raise PermissionDenied("only the owner can make a pharmacist link")
        if isinstance(hours, bool) or not isinstance(hours, int) or not MIN_H <= hours <= MAX_H:
            raise AuthProblem(f"A link lasts from {MIN_H} hour to {MAX_H} hours (7 days).", 400)
        if not await self.acc.hit(f"share|{agent}", 10, 3600):
            raise AuthProblem("Too many links. Wait a little.", 429)
        mem = self.gm.open(agent, circle)
        person = await mem._known_person(person)
        now = now_ms()
        active = (await self._q("MATCH (s:Share {circle:$c}) WHERE s.exp > $n AND NOT s.revoked RETURN count(s)", {"c": circle, "n": now}))[0][0]
        if active >= MAX_ACTIVE:
            raise AuthProblem("Three links are already open. Revoke one first.", 409)
        token = "ps_" + secrets.token_urlsafe(24)
        sid = new_id("share")
        await self._q("CREATE (:Share {id:$id, hash:$h, circle:$c, person:$p, by:$by, created:$n, exp:$e, note:$note, views:0, revoked:false})",
                      {"id": sid, "h": _sha(token), "c": circle, "p": norm(person), "by": agent, "n": now, "e": now + hours * 3_600_000, "note": " ".join(note.split())[:120]})
        return {"id": sid, "token": token, "path": f"/share/{token}", "expires_at": now + hours * 3_600_000, "hours": hours,
                "note": "This is shown once. Anyone who has the link can read what it shows until it expires or you revoke it."}

    async def list(self, agent: str, circle: str) -> list[dict]:
        if await self.acc.role(agent, circle) is None:
            raise PermissionDenied("not in this circle")
        rows = await self._q("MATCH (s:Share {circle:$c}) RETURN s.id, s.created, s.exp, s.views, s.revoked, s.note ORDER BY s.created DESC LIMIT 20", {"c": circle})
        now = now_ms()
        return [{"id": r[0], "created": r[1], "expires_at": r[2], "views": r[3], "revoked": bool(r[4]), "active": r[2] > now and not r[4], "note": r[5]} for r in rows]

    async def revoke(self, agent: str, circle: str, share_id: str) -> dict:
        if await self.acc.role(agent, circle) != "owner":
            raise PermissionDenied("only the owner can revoke a link")
        rows = await self._q("MATCH (s:Share {id:$i, circle:$c}) SET s.revoked = true RETURN s.id", {"i": share_id, "c": circle})
        if not rows:
            raise AuthProblem("No such link.", 404)
        return {"revoked": share_id}

    # ------------------------------------------------------------------ the viewer's side (no account: the secret is the key)
    async def _open(self, token: str) -> Optional[dict]:
        if not token or not token.startswith("ps_") or len(token) > 80:
            return None
        rows = await self._q("MATCH (s:Share {hash:$h}) WHERE s.exp > $n AND NOT s.revoked RETURN s.id, s.circle, s.person, s.by, s.exp", {"h": _sha(token), "n": now_ms()})
        if not rows:
            return None
        sid, circle, person, by, exp = rows[0]
        if await self.acc.role(by, circle) != "owner":              # the maker is no longer the owner: the link stops with them
            return None
        return {"id": sid, "circle": circle, "person": person, "by": by, "exp": exp}

    async def view(self, token: str, ip: str = "") -> Optional[dict]:
        s = await self._open(token)
        if s is None:
            return None
        if not await self.acc.hit(f"shareview|{_sha(token)[:16]}|{ip}", 120, 3600):
            raise AuthProblem("Too many requests for this link.", 429)
        await self._q("MATCH (x:Share {id:$i}) SET x.views = x.views + 1", {"i": s["id"]})
        mem = self.gm.open(s["by"], s["circle"])
        reg = await mem.care_regimen(s["person"])
        chk = await mem.care_check(s["person"])
        allergy = await mem.care_allergy_check(s["person"])
        return {
            "person": s["person"], "as_of": now_ms(), "expires_at": s["exp"],
            "medicines": [{"drug": r["drug"], "product": r.get("product") or "", "dose_text": r["dose_text"], "freq_text": r["freq_text"], "times": r["slots"],
                           "as_needed": r["as_needed"], "ends_on": r["ends_on"], "entered_by": HOW.get(r["source"], r["source"]),
                           "quote_verified": bool(r.get("verified"))} for r in reg],
            "flags": [{"kind": "direct", "drugs": f["drugs"], "level": f["level"], "source": f["source"]} for f in chk["direct"]]
                     + [{"kind": "enzyme", "meaning": f["meaning"]} for f in chk["enzyme_paths"]],
            "possible_duplicates": [d["meaning"] for d in chk.get("duplicates", [])],
            "unchecked": [u if isinstance(u, str) else str(u.get("drug", "")) for u in chk.get("unchecked", [])],
            "allergy_matches": [{"allergy": h["allergy"], "drug": h["drug"], "why": h["why"]} for h in allergy["hits"]],
            "statement": chk["judgement"]["statement"],
            "note": "Read from a family's own record, which is what they typed or read from labels. A cross-check against public sources, not clinical advice, and not a statement that anything is safe.",
        }

    async def review(self, token: str, name: str, note: str) -> dict:
        s = await self._open(token)
        if s is None:
            raise AuthProblem("This link is not open any more.", 404)
        if not await self.acc.hit(f"sharerev|{_sha(token)[:16]}", 10, 3600):
            raise AuthProblem("Too many notes for this link.", 429)
        try:
            return await self.gm.open(s["by"], s["circle"]).care_add_review(s["person"], name, note, s["id"])
        except ValueError as e:
            raise AuthProblem(str(e), 400)


# ---------------------------------------------------------------------- the page (server-rendered, every value escaped)
def render(v: dict) -> str:
    e = html.escape

    def li(x: str) -> str:
        return f"<li>{e(x)}</li>"

    def row(m: dict) -> str:
        product = f" <small>({e(m['product'])})</small>" if m["product"] else ""
        often = e(m["freq_text"]) + (" · " + e(", ".join(m["times"])) if m["times"] else "") + (" · as needed" if m["as_needed"] else "") + (" · until " + e(m["ends_on"]) if m["ends_on"] else "")
        return (f"<tr><td>{e(m['drug'].title())}{product}</td><td>{e(m['dose_text'])}</td><td>{often}</td>"
                f"<td>{e(m['entered_by'])}{' · line verified' if m['quote_verified'] else ''}</td></tr>")

    meds = "".join(row(m) for m in v["medicines"]) or "<tr><td colspan=4>Nothing on record.</td></tr>"
    flags = "".join(li(f"{' + '.join(d.title() for d in f['drugs'])}: {f['level']} ({f['source']})") if f["kind"] == "direct" else li(f["meaning"]) for f in v["flags"]) \
        or "<li>No flag from the public sources used.</li>"
    dups = "".join(li(d) for d in v["possible_duplicates"])
    unchecked = "".join(li(f"{u.title()} was not checked: it is not in the reference data.") for u in v["unchecked"])
    allergies = "".join(li(f"{a['allergy']}: {a['drug'].title()} ({a['why']})") for a in v["allergy_matches"])
    exp = time.strftime("%d %b %Y %H:%M UTC", time.gmtime(v["expires_at"] / 1000))
    extra = ""
    if dups:
        extra += f"<h3>Possible duplicates</h3><ul>{dups}</ul>"
    if unchecked:
        extra += f"<h3>Not checked</h3><ul>{unchecked}</ul>"
    if allergies:
        extra += f"<h3>Recorded allergies that match</h3><ul>{allergies}</ul>"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow"><title>Medicines on record</title>'
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:0 auto;padding:1rem;color:#1c1b1f;background:#fff}table{border-collapse:collapse;width:100%}"
        "td,th{border-bottom:1px solid #ddd;padding:.4rem;text-align:left;vertical-align:top}.note{background:#f3f1f6;padding:.7rem;border-radius:.5rem}"
        "label{display:block;margin:.6rem 0 .2rem}input,textarea{width:100%;font:inherit;padding:.4rem;box-sizing:border-box}button{font:inherit;padding:.5rem 1rem;margin-top:.6rem}</style></head><body>"
        f"<h1>Medicines on record for {e(v['person'].title())}</h1>"
        f"<p class=\"note\">{e(v['note'])}<br>{e(v['statement'])}<br>This link closes on {e(exp)}.</p>"
        f"<table><thead><tr><th>Medicine</th><th>Dose</th><th>How often</th><th>Entered</th></tr></thead><tbody>{meds}</tbody></table>"
        f"<h2>Cross-checks</h2><ul>{flags}</ul>{extra}"
        '<h2>Leave a note for the family</h2><form id="f"><label for="n">Your name (typed, not verified)</label><input id="n" maxlength="60" required>'
        '<label for="t">Note (optional)</label><textarea id="t" maxlength="300" rows="3"></textarea><button type="submit">Send</button><p id="m" role="status"></p></form>'
        "<script>document.getElementById('f').addEventListener('submit',async function(ev){ev.preventDefault();"
        "var r=await fetch(location.pathname.replace('/share/','/v1/share/')+'/review',{method:'POST',headers:{'content-type':'application/json'},"
        "body:JSON.stringify({name:document.getElementById('n').value,note:document.getElementById('t').value})});"
        "document.getElementById('m').textContent=r.ok?'Thank you. The family will see your name and note.':'Could not send it.';});</script></body></html>"
    )
