"""Cookie sessions (CC_COOKIE_SESSIONS=1): the session lives in an httpOnly cookie, state-changing calls need the CSRF header, bearer keys are unchanged."""
import uuid

import httpx
import pytest_asyncio

from graphmem import accounts_api
from test_accounts import PW, auth
from graphmem.api import create_app
from test_api import client as plain_client  # noqa: F401 (fixture)


@pytest_asyncio.fixture
async def client(gm):
    """A client with a cookie jar that accepts cookies (the shared fixture's host has a single-label name, which a cookie jar refuses)."""
    app = create_app(gm, admin_key="admin-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.test") as c:
        yield c


def mail():
    return f"ck-{uuid.uuid4().hex[:8]}@ck.test"


async def test_with_the_flag_off_nothing_changes(client):
    r = await client.post("/v1/auth/signup", json={"email": mail(), "password": PW, "name": "Off"})
    assert r.status_code == 200 and r.json()["token"].startswith("cs_") and "set-cookie" not in r.headers
    assert (await client.get("/v1/auth/config")).json()["cookie_sessions"] is False


async def test_the_session_is_an_httponly_cookie_and_a_page_script_never_sees_the_token(client, monkeypatch):
    monkeypatch.setattr(accounts_api, "COOKIE_MODE", True)
    r = await client.post("/v1/auth/signup", json={"email": mail(), "password": PW, "name": "On"})
    assert r.status_code == 200
    assert r.json()["token"] == "cookie" and "cs_" not in r.text                         # the body carries no usable token
    cookies = r.headers.get_list("set-cookie")
    sess = next(c for c in cookies if c.startswith("cc_session="))
    csrf = next(c for c in cookies if c.startswith("cc_csrf="))
    assert "httponly" in sess.lower() and "samesite=lax" in sess.lower()
    assert "httponly" not in csrf.lower()                                                # the page has to read this one
    assert (await client.get("/v1/account")).status_code == 200                          # the cookie alone authenticates a read
    token = sess.split(";")[0].split("=", 1)[1]
    assert (await client.get("/v1/account", headers=auth(token))).status_code == 200      # a bearer token still works
    assert (await client.get("/v1/auth/config")).json()["cookie_sessions"] is True


async def test_a_change_made_with_only_the_cookie_needs_the_csrf_header_and_a_same_site_origin(client, monkeypatch):
    monkeypatch.setattr(accounts_api, "COOKIE_MODE", True)
    await client.post("/v1/auth/signup", json={"email": mail(), "password": PW, "name": "Cs"})
    token = client.cookies.get("cc_csrf")
    body = {"name": "Home", "person": "Mum"}
    assert (await client.post("/v1/account/circles", json=body)).status_code == 403                       # a cross-site form could send the cookie, not the header
    assert (await client.post("/v1/account/circles", json=body, headers={"x-cc-csrf": "wrong"})).status_code == 403
    assert (await client.post("/v1/account/circles", json=body, headers={"x-cc-csrf": token, "origin": "https://evil.example"})).status_code == 403
    ok = await client.post("/v1/account/circles", json=body, headers={"x-cc-csrf": token, "origin": "http://app.test"})
    assert ok.status_code == 200, ok.text


async def test_bearer_keys_need_no_csrf_header_and_signing_out_ends_the_cookie_session(client, monkeypatch):
    monkeypatch.setattr(accounts_api, "COOKIE_MODE", True)
    r = await client.post("/v1/auth/signup", json={"email": mail(), "password": PW, "name": "So"})
    real = next(c for c in r.headers.get_list("set-cookie") if c.startswith("cc_session=")).split(";")[0].split("=", 1)[1]
    csrf = client.cookies.get("cc_csrf")
    assert (await client.post("/v1/account/circles", headers=auth(real), json={"name": "B", "person": "Dad"})).status_code == 200   # bearer: no header needed
    out = await client.post("/v1/auth/signout", headers={"x-cc-csrf": csrf})
    assert out.status_code == 200 and any("cc_session=" in c and ("max-age=0" in c.lower() or "expires" in c.lower()) for c in out.headers.get_list("set-cookie"))
    assert (await client.get("/v1/account", headers=auth(real))).status_code == 401                                                # the session itself is gone


async def test_changing_the_password_keeps_the_session_that_changed_it(client, monkeypatch):
    monkeypatch.setattr(accounts_api, "COOKIE_MODE", True)
    await client.post("/v1/auth/signup", json={"email": mail(), "password": PW, "name": "Pw"})
    csrf = client.cookies.get("cc_csrf")
    r = await client.post("/v1/account/password", json={"old": PW, "new": "another-pass9"}, headers={"x-cc-csrf": csrf})
    assert r.status_code == 200, r.text
    assert (await client.get("/v1/account")).status_code == 200                       # this browser is still signed in
