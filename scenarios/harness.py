"""A tiny harness for scenario testing: real accounts, real HTTP, real permission checks. A scenario is a function that plays out something a person
(or a misbehaving client) could really do and states what must be true afterwards. Failures are collected, not raised, so one run shows every problem."""
import json
import os
import random
import string
import time
import traceback
import urllib.parse

import httpx

BASE = os.getenv("SCENARIO_URL", "http://localhost:8099")
PW = "scenario-pass1"
RESULTS: list[dict] = []
H = 3_600_000


def rid(n=6):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


class User:
    def __init__(self, world, name, email, token, agent):
        self.w, self.name, self.email, self.token, self.agent = world, name, email, token, agent

    @property
    def h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path, **kw):
        return self.w.http.get(path, headers=self.h, **kw)

    def post(self, path, body=None, **kw):
        return self.w.http.post(path, json=body or {}, headers=self.h, **kw)

    def delete(self, path, body=None):
        return self.w.http.request("DELETE", path, json=body or {}, headers=self.h)

    def op(self, circle, op, **args):
        """Run an operation on a circle; returns (status, result-or-error)."""
        r = self.w.http.post(f"/v1/tenants/{circle}/{op}", json=args, headers=self.h)
        try:
            b = r.json()
        except Exception:
            b = r.text
        return r.status_code, (b.get("result") if isinstance(b, dict) and "result" in b else b)

    def ok(self, circle, op, **args):
        s, b = self.op(circle, op, **args)
        assert s == 200, f"{op} {args} -> {s} {str(b)[:160]}"
        return b


class World:
    def __init__(self):
        self.http = httpx.Client(base_url=BASE, timeout=60)
        self.tag = rid()

    def user(self, name, pw=PW):
        email = f"{name.lower()}-{self.tag}-{rid(3)}@scenario.test"
        r = self.http.post("/v1/auth/signup", json={"email": email, "password": pw, "name": name})
        assert r.status_code == 200, f"signup {name}: {r.status_code} {r.text[:120]}"
        j = r.json()
        return User(self, name, email, j["token"], j["account"]["id"])

    def circle(self, owner, name="Mum's medicines", person="Mum"):
        r = owner.post("/v1/account/circles", {"name": name, "person": person})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def join(self, owner, circle, carer):
        code = owner.post(f"/v1/circles/{circle}/invites").json()["code"]
        r = carer.post("/v1/join", {"code": code})
        assert r.status_code == 200, r.text
        return r.json()

    def team(self, person="Mum"):
        """Priya owns a circle for Mum; Omar is a second carer; Mallory has an account but no part in it."""
        priya, omar, mallory = self.user("Priya"), self.user("Omar"), self.user("Mallory")
        c = self.circle(priya, "Mum's medicines", person)
        self.join(priya, c, omar)
        return priya, omar, mallory, c


class Run:
    def __init__(self, sid, title):
        self.sid, self.title, self.checks = sid, title, []

    def check(self, cond, expect, got=""):
        self.checks.append({"ok": bool(cond), "expect": expect, "got": "" if cond else str(got)[:300]})
        return bool(cond)


def scenario(sid, title):
    def deco(fn):
        fn.sid, fn.title = sid, title
        SCENARIOS.append(fn)
        return fn
    return deco


SCENARIOS: list = []


def run_all(only=None):
    world = World()
    for fn in SCENARIOS:
        if only and not fn.sid.startswith(only):
            continue
        run = Run(fn.sid, fn.title)
        t0 = time.perf_counter()
        try:
            fn(world, run)
        except AssertionError as e:
            run.check(False, "no setup step failed", e)
        except Exception as e:
            run.check(False, "the scenario ran to the end", f"{type(e).__name__}: {e} @ {traceback.format_exc().splitlines()[-3].strip()}")
        bad = [c for c in run.checks if not c["ok"]]
        RESULTS.append({"sid": run.sid, "title": run.title, "checks": len(run.checks), "failed": bad, "secs": time.perf_counter() - t0})
        mark = "PASS" if not bad else "FAIL"
        print(f"[{mark}] {run.sid:<5} {run.title}  ({len(run.checks)} checks)")
        for c in bad:
            print(f"        x expected: {c['expect']}\n          got: {c['got']}")
    total = sum(r["checks"] for r in RESULTS)
    failed = sum(len(r["failed"]) for r in RESULTS)
    print(f"\n{len(RESULTS)} scenarios, {total} checks, {failed} failed")
    return failed
