"""Accounts, profiles, circles, invitations, Cognito exchange. Everything is read back from the server: nothing here is a mock of the data."""
import time

import httpx
import pytest
import pytest_asyncio

from carecircle import accounts as accmod
from carecircle import cognito as cog
from graphmem.api import create_app
from test_api import ADMIN, client  # noqa: F401 (fixture)

PW = "correct-horse1"


async def signup(client, email, name="Priya", pw=PW):
    r = await client.post("/v1/auth/signup", json={"email": email, "password": pw, "name": name})
    return r


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def account(client, email="priya@tt.test", name="Priya"):
    r = await signup(client, email, name)
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["account"]


async def test_signup_signin_profile_and_nothing_secret_is_stored(client, gm):
    token, acct = await account(client)
    assert token.startswith("cs_") and acct["email"] == "priya@tt.test" and acct["id"].startswith("priya-")
    me = (await client.get("/v1/account", headers=auth(token))).json()
    assert me["name"] == "Priya" and me["circles"] == [] and me["telegram"] == []
    ctl = gm.db.client.select_graph("ctl")
    row = (await ctl.query("MATCH (a:Account {email:'priya@tt.test'}) RETURN a.hash, a.salt")).result_set[0]
    assert PW not in row[0] and len(row[0]) == 64 and row[1]                   # scrypt hash, not the password
    sessions = (await ctl.query("MATCH (s:Session) RETURN s.hash")).result_set
    assert token not in [r[0] for r in sessions]                               # only the token's SHA-256
    r = await client.post("/v1/auth/signin", json={"email": "PRIYA@tt.test", "password": PW})     # email is case-insensitive
    assert r.status_code == 200 and r.json()["token"] != token


async def test_password_rules_duplicates_and_generic_signin_failure(client):
    assert (await signup(client, "a@tt.test", pw="short1")).status_code == 400
    assert (await signup(client, "a@tt.test", pw="longpassword")).status_code == 400          # no digit
    assert (await signup(client, "not-an-email", pw=PW)).status_code == 400
    await account(client, "b@tt.test", "Bo")
    assert (await signup(client, "b@tt.test", "Bo")).status_code == 409
    wrong = await client.post("/v1/auth/signin", json={"email": "b@tt.test", "password": "nope-nope1"})
    ghost = await client.post("/v1/auth/signin", json={"email": "ghost@tt.test", "password": "nope-nope1"})
    assert wrong.status_code == ghost.status_code == 401 and wrong.json() == ghost.json()      # no way to learn who has an account


async def test_repeated_bad_signins_are_throttled(client):
    await account(client, "c@tt.test", "Cy")
    codes = [(await client.post("/v1/auth/signin", json={"email": "c@tt.test", "password": "bad-pass1"})).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    assert (await client.post("/v1/auth/signin", json={"email": "c@tt.test", "password": PW})).status_code == 429     # even the right one waits


async def test_profile_edit_password_change_and_signout(client):
    token, _ = await account(client)
    assert (await client.patch("/v1/account", json={"name": "Priya S"}, headers=auth(token))).json()["name"] == "Priya S"
    assert (await client.patch("/v1/account", json={"name": "  "}, headers=auth(token))).status_code == 400
    assert (await client.post("/v1/account/password", json={"old": "wrong-one1", "new": "another-pass2"}, headers=auth(token))).status_code == 401
    other = (await client.post("/v1/auth/signin", json={"email": "priya@tt.test", "password": PW})).json()["token"]      # a second device
    assert (await client.post("/v1/account/password", json={"old": PW, "new": "another-pass2"}, headers=auth(token))).status_code == 200
    assert (await client.get("/v1/account", headers=auth(token))).status_code == 200           # the device that changed it stays signed in
    assert (await client.get("/v1/account", headers=auth(other))).status_code == 401           # every other device must sign in again
    t2 = (await client.post("/v1/auth/signin", json={"email": "priya@tt.test", "password": "another-pass2"})).json()["token"]
    assert (await client.post("/v1/auth/signout", headers=auth(t2))).status_code == 200
    assert (await client.get("/v1/account", headers=auth(t2))).status_code == 401


async def test_circle_lifecycle_data_is_real_and_isolated(client):
    owner, _ = await account(client, "owner@tt.test", "Olive")
    other, _ = await account(client, "other@tt.test", "Omar")
    c = (await client.post("/v1/account/circles", json={"name": "Asha's family", "person": "Asha"}, headers=auth(owner))).json()
    assert c["role"] == "owner" and c["person"] == "asha" and c["members"] == 1
    cid = c["id"]
    ops = f"/v1/tenants/{cid}"
    assert (await client.post(f"{ops}/care_people", json={}, headers=auth(owner))).json()["result"]["patients"] == ["asha"]    # the person exists from the start
    assert (await client.post(f"{ops}/care_regimen", json={"person": "asha"}, headers=auth(owner))).json()["result"] == []      # and nothing else is invented
    assert (await client.post(f"{ops}/care_regimen", json={"person": "asha"}, headers=auth(other))).status_code == 403         # a stranger sees nothing
    r = await client.post(f"{ops}/care_record", json={"person": "asha", "drug": "metformin", "dose_text": "500 mg"}, headers=auth(owner))
    assert r.status_code == 200
    inv = (await client.post(f"/v1/circles/{cid}/invites", headers=auth(owner))).json()
    assert len(inv["code"]) == 9 and inv["code"][4] == "-"
    assert (await client.post(f"/v1/circles/{cid}/invites", headers=auth(other))).status_code == 403                             # only the owner invites
    j = await client.post("/v1/join", json={"code": inv["code"].lower()}, headers=auth(other))
    assert j.status_code == 200 and j.json()["role"] == "carer" and j.json()["members"] == 2
    assert (await client.post("/v1/join", json={"code": inv["code"]}, headers=auth(other))).status_code == 404                  # one use only
    assert [d["drug"] for d in (await client.post(f"{ops}/care_regimen", json={"person": "asha"}, headers=auth(other))).json()["result"]] == ["metformin"]
    members = (await client.get(f"/v1/circles/{cid}/members", headers=auth(other))).json()
    assert [(m["name"], m["role"]) for m in members] == [("Olive", "owner"), ("Omar", "carer")] and members[1]["you"]
    assert (await client.patch(f"/v1/circles/{cid}", json={"name": "Renamed"}, headers=auth(other))).status_code == 403
    assert (await client.patch(f"/v1/circles/{cid}", json={"name": "Renamed"}, headers=auth(owner))).status_code == 200
    # the owner leaves: ownership passes to the other carer, who can now invite and erase
    assert (await client.post(f"/v1/circles/{cid}/leave", headers=auth(owner))).json() == {"deleted_circle": False}
    assert (await client.post(f"{ops}/care_regimen", json={"person": "asha"}, headers=auth(owner))).status_code == 403
    mine = (await client.get("/v1/account/circles", headers=auth(other))).json()
    assert mine[0]["role"] == "owner" and mine[0]["name"] == "Renamed" and mine[0]["members"] == 1
    assert (await client.post(f"/v1/circles/{cid}/invites", headers=auth(other))).status_code == 200
    # the last member leaving deletes the circle and its graph
    assert (await client.post(f"/v1/circles/{cid}/leave", headers=auth(other))).json() == {"deleted_circle": True}
    assert (await client.get("/v1/account/circles", headers=auth(other))).json() == []


async def test_owner_removes_a_carer_and_a_carer_cannot(client):
    a, _ = await account(client, "a@tt.test", "Ana")
    b, bacct = await account(client, "b@tt.test", "Ben")
    cid = (await client.post("/v1/account/circles", json={"name": "C", "person": "Mum"}, headers=auth(a))).json()["id"]
    code = (await client.post(f"/v1/circles/{cid}/invites", headers=auth(a))).json()["code"]
    await client.post("/v1/join", json={"code": code}, headers=auth(b))
    me_a = (await client.get("/v1/account", headers=auth(a))).json()["id"]
    assert (await client.delete(f"/v1/circles/{cid}/members/{me_a}", headers=auth(b))).status_code == 403
    assert (await client.delete(f"/v1/circles/{cid}/members/{bacct['id']}", headers=auth(a))).status_code == 200
    assert (await client.get(f"/v1/circles/{cid}/members", headers=auth(b))).status_code == 403


async def test_delete_account_removes_sole_circles_and_hands_over_shared_ones(client, gm):
    a, aacct = await account(client, "a@tt.test", "Ana")
    b, _ = await account(client, "b@tt.test", "Ben")
    solo = (await client.post("/v1/account/circles", json={"name": "Solo", "person": "Dad"}, headers=auth(a))).json()["id"]
    shared = (await client.post("/v1/account/circles", json={"name": "Shared", "person": "Mum"}, headers=auth(a))).json()["id"]
    await client.post("/v1/join", json={"code": (await client.post(f"/v1/circles/{shared}/invites", headers=auth(a))).json()["code"]}, headers=auth(b))
    assert (await client.request("DELETE", "/v1/account", json={"confirm": "wrong@x.y"}, headers=auth(a))).status_code == 400
    r = await client.request("DELETE", "/v1/account", json={"confirm": "A@tt.test"}, headers=auth(a))
    assert r.status_code == 200 and r.json() == {"deleted": True, "circles_deleted": 1}
    assert (await client.get("/v1/account", headers=auth(a))).status_code == 401
    assert [c["id"] for c in (await client.get("/v1/account/circles", headers=auth(b))).json()] == [shared]
    assert (await client.get("/v1/account/circles", headers=auth(b))).json()[0]["role"] == "owner"
    assert solo not in await gm.db.list_tenant_graphs()
    assert (await client.post("/v1/auth/signin", json={"email": "a@tt.test", "password": PW})).status_code == 401


async def test_telegram_code_is_one_time_and_listed(client, gm):
    token, acct = await account(client)
    code = (await client.post("/v1/account/telegram-code", headers=auth(token))).json()["code"]
    assert len(code) == 6
    accs = accmod.Accounts(gm)
    assert await accs.redeem_telegram_code(code.lower()) == acct["id"]
    assert await accs.redeem_telegram_code(code) is None                       # used once


async def test_demo_accounts_are_seeded_once_and_work_like_any_other(client, gm, monkeypatch):
    from carecircle import demo
    accs = accmod.Accounts(gm)
    cleanup = []
    try:
        await demo.seed_shared(gm, accs)
        await demo.seed_shared(gm, accs)                                       # idempotent
        cfg = (await client.get("/v1/auth/config")).json()
        assert cfg["provider"] == "local" and [d["email"] for d in cfg["demo_accounts"]] == [e for e, _ in accmod.DEMO_ACCOUNTS]
        r = await client.post("/v1/auth/signin", json={"email": cfg["demo_accounts"][0]["email"], "password": cfg["demo_accounts"][0]["password"]})
        tok = r.json()["token"]
        circles = (await client.get("/v1/account/circles", headers=auth(tok))).json()
        assert circles[0]["id"] == accmod.SHARED_CIRCLE and circles[0]["demo"] and circles[0]["members"] == 2
        reg = (await client.post(f"/v1/tenants/{accmod.SHARED_CIRCLE}/care_regimen", json={"person": "asha"}, headers=auth(tok))).json()["result"]
        assert {"metformin", "warfarin", "levothyroxine", "vitamin d"} <= {x["drug"] for x in reg} and len(reg) == 10          # ten weeks of history, not a stub
        assert (await client.request("DELETE", "/v1/account", json={"confirm": cfg["demo_accounts"][0]["email"]}, headers=auth(tok))).status_code == 403
        await client.post(f"/v1/tenants/{accmod.SHARED_CIRCLE}/care_record", json={"person": "asha", "drug": "tramadol"}, headers=auth(tok))
        assert (await client.post("/v1/demo/reset", headers=auth(tok))).status_code == 200
        reg = (await client.post(f"/v1/tenants/{accmod.SHARED_CIRCLE}/care_regimen", json={"person": "asha"}, headers=auth(tok))).json()["result"]
        assert "tramadol" not in {x["drug"] for x in reg} and len(reg) == 10
        other, _ = await account(client)
        assert (await client.post("/v1/demo/reset", headers=auth(other))).status_code == 403
    finally:
        await gm.db.drop_tenant(accmod.SHARED_CIRCLE)
        ctl = await gm._ctl()
        await ctl.query("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": accmod.SHARED_CIRCLE})
        for email, _ in accmod.DEMO_ACCOUNTS:
            await ctl.query("MATCH (a:Account {email:$e}) OPTIONAL MATCH (a)<-[:OF]-(s:Session) DETACH DELETE s, a", {"e": email})
            await ctl.query("MATCH (g:Agent) WHERE g.id STARTS WITH $p DETACH DELETE g", {"p": email.split("@")[0].split(".")[0] + "-"})


async def test_the_shared_demo_accounts_cannot_be_renamed_or_have_their_password_changed(client, gm):
    """Everyone is given the demo password on the sign-in page; if one visitor could change it or rename the account, the next visitor would be locked out."""
    from carecircle import demo
    accs = accmod.Accounts(gm)
    try:
        await demo.seed_shared(gm, accs)
        cfg = (await client.get("/v1/auth/config")).json()
        d = cfg["demo_accounts"][0]
        tok = (await client.post("/v1/auth/signin", json={"email": d["email"], "password": d["password"]})).json()["token"]
        assert (await client.patch("/v1/account", json={"name": "Hacked"}, headers=auth(tok))).status_code == 403
        r = await client.post("/v1/account/password", json={"old": d["password"], "new": "something-else-1"}, headers=auth(tok))
        assert r.status_code == 403
        assert (await client.get("/v1/account", headers=auth(tok))).json()["name"] != "Hacked"
        again = await client.post("/v1/auth/signin", json={"email": d["email"], "password": d["password"]})
        assert again.status_code == 200                                         # the published password still works for the next visitor
        mine, _ = await account(client)                                         # an ordinary account can still do both
        assert (await client.patch("/v1/account", json={"name": "Renamed"}, headers=auth(mine))).status_code == 200
    finally:
        await gm.db.drop_tenant(accmod.SHARED_CIRCLE)
        ctl = await gm._ctl()
        await ctl.query("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": accmod.SHARED_CIRCLE})
        for email, _ in accmod.DEMO_ACCOUNTS:
            await ctl.query("MATCH (a:Account {email:$e}) OPTIONAL MATCH (a)<-[:OF]-(s:Session) DETACH DELETE s, a", {"e": email})
            await ctl.query("MATCH (g:Agent) WHERE g.id STARTS WITH $p DETACH DELETE g", {"p": email.split("@")[0].split(".")[0] + "-"})


# ---------------------------------------------------------------- Cognito
def _rsa():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, **over):
    import jwt
    now = int(time.time())
    claims = {"sub": "sub-123", "email": "cog@tt.test", "email_verified": True, "token_use": "id", "aud": "client1",
              "iss": "https://cognito-idp.us-east-1.amazonaws.com/pool1", "iat": now, "exp": now + 3600, **over}
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


@pytest_asyncio.fixture
async def cognito_client(gm, monkeypatch):
    monkeypatch.setenv("CC_COGNITO_POOL_ID", "pool1")
    monkeypatch.setenv("CC_COGNITO_CLIENT_ID", "client1")
    monkeypatch.setenv("CC_COGNITO_REGION", "us-east-1")
    key = _rsa()

    class Fake:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()
    monkeypatch.setitem(cog._jwks, "https://cognito-idp.us-east-1.amazonaws.com/pool1", Fake())
    app = create_app(gm, admin_key="admin-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.key = key
        yield c


async def test_cognito_exchange_creates_the_account_once_and_rejects_bad_tokens(cognito_client):
    c = cognito_client
    cfg = (await c.get("/v1/auth/config")).json()
    assert cfg["provider"] == "cognito" and cfg["cognito"] == {"region": "us-east-1", "userPoolId": "pool1", "clientId": "client1"}
    assert (await signup(c, "x@tt.test")).status_code == 400                   # sign-up happens at Cognito, which emails the code
    r = await c.post("/v1/auth/exchange", json={"name": "Cora"}, headers=auth(_token(c.key)))
    assert r.status_code == 200 and r.json()["account"]["provider"] == "cognito" and r.json()["account"]["name"] == "Cora"
    r2 = await c.post("/v1/auth/exchange", json={}, headers=auth(_token(c.key)))
    assert r2.json()["account"]["id"] == r.json()["account"]["id"]            # the same person, not a second account
    assert (await c.get("/v1/account", headers=auth(r2.json()["token"]))).json()["email"] == "cog@tt.test"
    for bad in (_token(c.key, aud="other"), _token(c.key, iss="https://evil.example/pool1"), _token(c.key, exp=int(time.time()) - 10),
                _token(c.key, email_verified=False), _token(c.key, token_use="access"), _token(_rsa()), "garbage", ""):
        assert (await c.post("/v1/auth/exchange", json={}, headers=auth(bad))).status_code == 401, bad[:20]
    assert (await c.post("/v1/auth/exchange", json={}, headers=auth(_token(c.key, sub="sub-other")))).status_code == 409    # same email, different identity


async def test_only_an_owner_can_erase_everything_about_the_person(client):
    a, _ = await account(client, "a@tt.test", "Ana")
    b, _ = await account(client, "b@tt.test", "Ben")
    cid = (await client.post("/v1/account/circles", json={"name": "C", "person": "Mum"}, headers=auth(a))).json()["id"]
    await client.post("/v1/join", json={"code": (await client.post(f"/v1/circles/{cid}/invites", headers=auth(a))).json()["code"]}, headers=auth(b))
    erase = {"person": "mum", "confirm": "mum"}
    assert (await client.post(f"/v1/tenants/{cid}/care_forget_person", json=erase, headers=auth(b))).status_code == 403
    assert (await client.post(f"/v1/tenants/{cid}/care_forget_person", json=erase, headers=auth(a))).status_code == 200


async def test_telegram_links_with_an_account_code_and_switches_circles(client, gm):
    from carecircle.checks import Checker
    from carecircle.telegram import Bot

    class Api:
        def __init__(self): self.out = []
        def send(self, chat, text, buttons=None): self.out.append(text)

    token, acct = await account(client)
    c1 = (await client.post("/v1/account/circles", json={"name": "Asha", "person": "Asha"}, headers=auth(token))).json()["id"]
    c2 = (await client.post("/v1/account/circles", json={"name": "Dad", "person": "Dad"}, headers=auth(token))).json()["id"]
    api = Api()
    bot = Bot(gm, api, Checker())
    await bot.handle({"message": {"chat": {"id": 31}, "text": "/link NOPE12"}})
    assert "not valid" in api.out[-1]
    code = (await client.post("/v1/account/telegram-code", headers=auth(token))).json()["code"]
    await bot.handle({"message": {"chat": {"id": 31}, "text": f"/link {code}"}})
    assert "Linked to Asha" in api.out[-1]
    await bot.handle({"message": {"chat": {"id": 31}, "text": f"/link {code}"}})
    assert "not valid" in api.out[-1]                                                      # one use
    assert (await client.get("/v1/account", headers=auth(token))).json()["telegram"] == [{"chat": 31, "circle": c1}]
    await bot.handle({"message": {"chat": {"id": 31}, "text": "/circles"}})
    assert "1. Asha (here)" in api.out[-1] and "2. Dad" in api.out[-1]
    await bot.handle({"message": {"chat": {"id": 31}, "text": "/circles 2"}})
    assert "Now using Dad" in api.out[-1]
    await bot.handle({"message": {"chat": {"id": 31}, "text": "Please start warfarin 5 mg once daily"}})
    cb = [x for x in api.out if "I read: warfarin" in x]
    assert cb                                                                              # the proposal is for the circle now in use
    assert (await client.request("DELETE", "/v1/account/telegram", headers=auth(token))).status_code == 200
    assert (await client.get("/v1/account", headers=auth(token))).json()["telegram"] == []


async def test_members_count_as_carers_from_the_moment_they_join_and_stop_when_they_leave(client):
    a, _ = await account(client, "a@tt.test", "Ana")
    b, _ = await account(client, "b@tt.test", "Ben")
    cid = (await client.post("/v1/account/circles", json={"name": "C", "person": "Mum"}, headers=auth(a))).json()["id"]
    r = await client.post(f"/v1/tenants/{cid}/care_record", json={"person": "mum", "drug": "metformin"}, headers=auth(a))
    await client.post("/v1/join", json={"code": (await client.post(f"/v1/circles/{cid}/invites", headers=auth(a))).json()["code"]}, headers=auth(b))
    div = (await client.post(f"/v1/tenants/{cid}/care_divergence", json={"person": "mum"}, headers=auth(a))).json()["result"]
    assert sorted(k.split("-")[0] for k in div["carers"]) == ["ana", "ben"]
    ben = next(k for k in div["carers"] if k.startswith("ben"))
    assert [u["drug"] for u in div["carers"][ben]["unacknowledged"]] == ["metformin"]            # Ben has not seen Ana's entry
    await client.post(f"/v1/tenants/{cid}/care_ack", json={"dose_id": r.json()["result"]["id"]}, headers=auth(b))
    await client.post(f"/v1/circles/{cid}/leave", headers=auth(b))
    div = (await client.post(f"/v1/tenants/{cid}/care_divergence", json={"person": "mum"}, headers=auth(a))).json()["result"]
    assert [k.split("-")[0] for k in div["carers"]] == ["ana"]


async def test_owner_can_delete_a_circle_with_its_name_and_others_cannot(client, gm):
    a, _ = await account(client, "own@tt.test", "Own")
    b, _ = await account(client, "car@tt.test", "Car")
    cid = (await client.post("/v1/account/circles", json={"name": "Nani's meds", "person": "Nani"}, headers=auth(a))).json()["id"]
    await client.post("/v1/join", json={"code": (await client.post(f"/v1/circles/{cid}/invites", headers=auth(a))).json()["code"]}, headers=auth(b))
    assert (await client.request("DELETE", f"/v1/circles/{cid}", json={"confirm": "Nani's meds"}, headers=auth(b))).status_code == 403      # a carer, not the owner
    assert (await client.request("DELETE", f"/v1/circles/{cid}", json={"confirm": "wrong"}, headers=auth(a))).status_code == 400
    assert cid in await gm.db.list_tenant_graphs()
    r = await client.request("DELETE", f"/v1/circles/{cid}", json={"confirm": "nani's  MEDS"}, headers=auth(a))
    assert r.status_code == 200 and r.json() == {"deleted_circle": True}
    assert cid not in await gm.db.list_tenant_graphs()
    assert (await client.get("/v1/account/circles", headers=auth(b))).json() == []                 # gone for the other carer too


async def test_sign_out_everywhere_ends_every_session(client):
    token, _ = await account(client, "multi@tt.test", "Multi")
    other = (await client.post("/v1/auth/signin", json={"email": "multi@tt.test", "password": PW})).json()["token"]
    assert (await client.get("/v1/account", headers=auth(other))).status_code == 200
    r = await client.post("/v1/account/signout-all", headers=auth(token))
    assert r.status_code == 200 and r.json()["signed_out"] == 2
    assert (await client.get("/v1/account", headers=auth(token))).status_code == 401
    assert (await client.get("/v1/account", headers=auth(other))).status_code == 401


async def test_account_export_holds_the_record_and_nothing_secret(client):
    token, _ = await account(client, "exp@tt.test", "Exp")
    cid = (await client.post("/v1/account/circles", json={"name": "Mum", "person": "Mum"}, headers=auth(token))).json()["id"]
    await client.post(f"/v1/tenants/{cid}/care_record", json={"person": "mum", "drug": "warfarin", "dose_text": "4 mg", "freq_text": "daily"}, headers=auth(token))
    r = await client.get("/v1/account/export", headers=auth(token))
    assert r.status_code == 200
    doc = r.json()
    assert doc["account"]["email"] == "exp@tt.test" and len(doc["circles"]) == 1
    c = doc["circles"][0]
    assert [x["drug"] for x in c["regimen"]] == ["warfarin"] and c["timeline"] and "readings" in c and "appointments" in c
    assert "hash" not in r.text and "salt" not in r.text and PW not in r.text
    assert (await client.get("/v1/account/export")).status_code == 401


async def test_quiet_hours_are_saved_validated_and_per_account(client):
    token, _ = await account(client, "q@tt.test", "Quin")
    assert (await client.get("/v1/account/quiet", headers=auth(token))).json() == {"from": None, "to": None, "tz": 0}
    r = await client.put("/v1/account/quiet", json={"start": 22, "end": 7, "tz": 330}, headers=auth(token))
    assert r.json() == {"from": 22, "to": 7, "tz": 330}
    assert (await client.put("/v1/account/quiet", json={"start": 25, "end": 7, "tz": 0}, headers=auth(token))).status_code == 400
    assert (await client.put("/v1/account/quiet", json={"start": 22, "tz": 0}, headers=auth(token))).status_code == 400      # needs both
    assert (await client.get("/v1/account/quiet", headers=auth(token))).json()["from"] == 22
    assert (await client.put("/v1/account/quiet", json={"tz": 0}, headers=auth(token))).json()["from"] is None             # off
    assert (await client.get("/v1/account/quiet")).status_code == 401


async def test_one_telegram_chat_per_account_the_newest_replaces_the_old(client, gm):
    from carecircle.checks import Checker
    from carecircle.telegram import Bot

    class Api:
        def __init__(self): self.out = []
        def send(self, chat, text, buttons=None): self.out.append((chat, text))

    token, acct = await account(client)
    c1 = (await client.post("/v1/account/circles", json={"name": "Asha", "person": "Asha"}, headers=auth(token))).json()["id"]
    api = Api()
    bot = Bot(gm, api, Checker())
    for chat in (41, 42):
        code = (await client.post("/v1/account/telegram-code", headers=auth(token))).json()["code"]
        await bot.handle({"message": {"chat": {"id": chat}, "text": f"/link {code}"}})
    assert (await client.get("/v1/account", headers=auth(token))).json()["telegram"] == [{"chat": 42, "circle": c1}]
    assert any(c == 41 and "unlinked" in t for c, t in api.out)                               # the old chat is told, not silently dropped
    await bot.handle({"message": {"chat": {"id": 41}, "text": "/regimen"}})
    assert "link this chat first" in api.out[-1][1].lower()                                   # and it no longer works
    code = (await client.post("/v1/account/telegram-code", headers=auth(token))).json()["code"]
    await bot.handle({"message": {"chat": {"id": 42}, "text": f"/link {code}"}})               # linking the same chat again changes nothing
    assert (await client.get("/v1/account", headers=auth(token))).json()["telegram"] == [{"chat": 42, "circle": c1}]
    assert (await client.request("DELETE", "/v1/account/telegram", headers=auth(token))).status_code == 200      # leave nothing linked behind


async def test_a_demo_circle_whose_build_was_interrupted_is_rebuilt_on_the_next_start(gm, monkeypatch):
    """If the process dies (or the build fails) halfway through seeding the shared demo circle, the next start must notice the circle is incomplete and
    rebuild it. It used to be marked as seeded before its history was built, so a half-built circle stayed half-built until someone pressed reset."""
    from carecircle import demo, demo_history
    accs = accmod.Accounts(gm)
    real_build = demo_history.build

    async def dies_halfway(ravi, meena, person, now):
        await ravi.care_record(person, "metformin", dose_text="500 mg", freq_text="twice daily", source_type="typed")          # something was written
        raise RuntimeError("the process was killed here")

    try:
        monkeypatch.setattr(demo_history, "build", dies_halfway)
        await gm.db.drop_tenant(accmod.SHARED_CIRCLE)
        await accs._q("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": accmod.SHARED_CIRCLE})
        with pytest.raises(RuntimeError, match="killed"):
            await demo.seed_shared(gm, accs)
        monkeypatch.setattr(demo_history, "build", real_build)
        await demo.seed_shared(gm, accs)                                              # the next start
        ravi = gm.open(accs and (await accs.by_email(accmod.DEMO_ACCOUNTS[0][0]))["agent"], accmod.SHARED_CIRCLE)
        reg = await ravi.care_regimen("asha")
        assert len(reg) == 10 and {"warfarin", "levothyroxine"} <= {x["drug"] for x in reg}            # the whole story, not the one entry the dead build left
    finally:
        monkeypatch.setattr(demo_history, "build", real_build)
        await gm.db.drop_tenant(accmod.SHARED_CIRCLE)                                    # leave nothing behind, as the sibling test does
        ctl = await gm._ctl()
        await ctl.query("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": accmod.SHARED_CIRCLE})
        for email, _ in accmod.DEMO_ACCOUNTS:
            await ctl.query("MATCH (a:Account {email:$e}) OPTIONAL MATCH (a)<-[:OF]-(s:Session) DETACH DELETE s, a", {"e": email})
            await ctl.query("MATCH (g:Agent) WHERE g.id STARTS WITH $p DETACH DELETE g", {"p": email.split("@")[0].split(".")[0] + "-"})


async def test_the_demo_circle_is_built_on_an_empty_graph_even_if_an_old_one_was_left_behind(gm):
    """The circle's graph can outlive its record in the control graph (a half-cleaned database, a restore). Seeding must not write the story on top of
    the old data: a medicine already stopped there made the new story's own `stop` fail."""
    from carecircle import demo
    accs = accmod.Accounts(gm)
    try:
        await gm.db.drop_tenant(accmod.SHARED_CIRCLE)
        ctl = await gm._ctl()
        await ctl.query("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": accmod.SHARED_CIRCLE})
        await demo.seed_shared(gm, accs)
        await ctl.query("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": accmod.SHARED_CIRCLE})          # the record goes, the graph stays
        await demo.seed_shared(gm, accs)
        ravi = gm.open((await accs.by_email(accmod.DEMO_ACCOUNTS[0][0]))["agent"], accmod.SHARED_CIRCLE)
        assert len(await ravi.care_regimen("asha")) == 10
    finally:
        await gm.db.drop_tenant(accmod.SHARED_CIRCLE)
        ctl = await gm._ctl()
        await ctl.query("MATCH (t:Tenant {id:$c}) DETACH DELETE t", {"c": accmod.SHARED_CIRCLE})
        for email, _ in accmod.DEMO_ACCOUNTS:
            await ctl.query("MATCH (a:Account {email:$e}) OPTIONAL MATCH (a)<-[:OF]-(s:Session) DETACH DELETE s, a", {"e": email})
            await ctl.query("MATCH (g:Agent) WHERE g.id STARTS WITH $p DETACH DELETE g", {"p": email.split("@")[0].split(".")[0] + "-"})
