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
# Against a site that signs in with Amazon Cognito, set SCENARIO_COGNITO=<pool id>:<app client id> (AWS credentials in the environment): every user is then
# a throwaway Cognito user with a made-up address, signed in the way the web page does, and removed again (account, circles, Cognito user) at the end.
COGNITO = os.getenv("SCENARIO_COGNITO", "")
# These sign up and sign in with the app's own passwords, which a Cognito site does not offer.
LOCAL_ONLY = {"A1", "A2", "A3", "S2", "N1"}
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
        self.made: list[User] = []
        if COGNITO:
            import boto3
            self.pool, self.client_id = COGNITO.split(":", 1)
            self.cog = boto3.client("cognito-idp", region_name=self.pool.split("_")[0])

    def user(self, name, pw=PW):
        email = f"{name.lower()}-{self.tag}-{rid(3)}@scenario.test"
        if COGNITO:
            return self._cognito_user(name, email, pw)
        r = self.http.post("/v1/auth/signup", json={"email": email, "password": pw, "name": name})
        assert r.status_code == 200, f"signup {name}: {r.status_code} {r.text[:120]}"
        j = r.json()
        return User(self, name, email, j["token"], j["account"]["id"])

    def _cognito_user(self, name, email, pw):
        self.cog.admin_create_user(UserPoolId=self.pool, Username=email, MessageAction="SUPPRESS",
                                   UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}])
        self.cog.admin_set_user_password(UserPoolId=self.pool, Username=email, Password=pw + "A!", Permanent=True)
        tok = self.cog.initiate_auth(ClientId=self.client_id, AuthFlow="USER_PASSWORD_AUTH",
                                     AuthParameters={"USERNAME": email, "PASSWORD": pw + "A!"})["AuthenticationResult"]["IdToken"]
        r = self.http.post("/v1/auth/exchange", json={"name": name}, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, f"exchange {name}: {r.status_code} {r.text[:120]}"
        j = r.json()
        u = User(self, name, email, j["token"], j["account"]["id"])
        self.made.append(u)
        return u

    def cleanup(self):
        """Delete what a Cognito run made: each account with its circles, then the Cognito user. Returns how many could not be removed."""
        left = 0
        for u in self.made:
            try:
                r = self.http.request("DELETE", "/v1/account", json={"confirm": u.email}, headers=u.h)
                left += r.status_code not in (200, 401, 404)       # 401/404: the scenario already deleted that account
                self.cog.admin_delete_user(UserPoolId=self.pool, Username=u.email)
            except Exception as e:
                left += 1
                print(f"  cleanup failed for {u.email}: {type(e).__name__}: {e}")
        return left

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
    try:
        for fn in SCENARIOS:
            if only and not fn.sid.startswith(only):
                continue
            if COGNITO and fn.sid in LOCAL_ONLY:
                print(f"[SKIP] {fn.sid:<5} {fn.title}  (needs the app's own passwords)")
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
    finally:
        left = world.cleanup() if COGNITO else 0
        if COGNITO:
            print(f"cleanup: {len(world.made)} throwaway users, {left} not removed")

    total = sum(r["checks"] for r in RESULTS)
    failed = sum(len(r["failed"]) for r in RESULTS)
    print(f"\n{len(RESULTS)} scenarios, {total} checks, {failed} failed")
    return failed + left
