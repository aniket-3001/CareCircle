"""The pharmacist link: owner-made, expiring, revocable, read-only, nothing but the secret needed to read, nothing personal beyond the record."""
import uuid

from test_accounts import account, auth
from test_api import client  # noqa: F401 (fixture)


def mail(who):
    return f"{who}-{uuid.uuid4().hex[:8]}@sh.test"


async def circle_with_medicines(client, email=None):
    email = email or mail("own")
    token, acct = await account(client, email, "Owner")
    r = await client.post("/v1/account/circles", headers=auth(token), json={"name": "Home", "person": "Asha"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    for drug, dose in (("clarithromycin", "500 mg"), ("atorvastatin", "20 mg")):
        r = await client.post(f"/v1/tenants/{cid}/care_record", headers=auth(token), json={"person": "asha", "drug": drug, "dose_text": dose, "freq_text": "once daily", "source_type": "typed"})
        assert r.status_code == 200, r.text
    return token, cid


async def test_a_link_shows_the_record_and_checks_without_an_account_and_stores_only_a_hash(client, gm):
    token, cid = await circle_with_medicines(client)
    r = await client.post(f"/v1/circles/{cid}/shares", headers=auth(token), json={"person": "asha", "hours": 24, "note": "for the chemist"})
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["token"].startswith("ps_") and link["path"] == f"/share/{link['token']}"
    ctl = gm.db.client.select_graph("ctl")
    stored = (await ctl.query("MATCH (s:Share) RETURN s.hash")).result_set
    assert link["token"] not in [x[0] for x in stored] and len(stored[0][0]) == 64
    v = await client.get(link["path"])                                                        # no Authorization header at all
    assert v.status_code == 200 and v.headers["cache-control"] == "no-store" and "noindex" in v.headers["x-robots-tag"]
    page = v.text
    assert "Clarithromycin" in page and "Atorvastatin" in page and "not a statement that anything is safe" in page
    assert "Owner" not in page and "@sh.test" not in page                                  # no carer's name or address
    j = (await client.get(f"/v1/share/{link['token']}")).json()
    assert any(f["kind"] == "direct" and set(f["drugs"]) == {"clarithromycin", "atorvastatin"} for f in j["flags"]) and "quote" not in str(j["medicines"][0]).lower().replace("quote_verified", "")


async def test_a_link_expires_is_revoked_capped_and_owner_only(client, gm):
    token, cid = await circle_with_medicines(client)
    other, _ = await account(client, mail("carer"), "Carer")
    code = (await client.post(f"/v1/circles/{cid}/invites", headers=auth(token))).json()["code"]
    assert (await client.post("/v1/join", headers=auth(other), json={"code": code})).status_code == 200
    assert (await client.post(f"/v1/circles/{cid}/shares", headers=auth(other), json={"person": "asha"})).status_code == 403      # a carer cannot make one
    assert (await client.post(f"/v1/circles/{cid}/shares", headers=auth(token), json={"person": "asha", "hours": 0})).status_code == 400
    assert (await client.post(f"/v1/circles/{cid}/shares", headers=auth(token), json={"person": "ashaa"})).status_code in (400, 422)   # a near-miss name
    links = [(await client.post(f"/v1/circles/{cid}/shares", headers=auth(token), json={"person": "asha", "hours": 2})).json() for _ in range(3)]
    assert (await client.post(f"/v1/circles/{cid}/shares", headers=auth(token), json={"person": "asha"})).status_code == 409           # at most three open
    assert (await client.delete(f"/v1/circles/{cid}/shares/{links[0]['id']}", headers=auth(other))).status_code == 403
    assert (await client.delete(f"/v1/circles/{cid}/shares/{links[0]['id']}", headers=auth(token))).status_code == 200
    assert (await client.get(links[0]["path"])).status_code == 404                              # revoked
    assert (await client.get(links[1]["path"])).status_code == 200
    ctl = gm.db.client.select_graph("ctl")
    await ctl.query("MATCH (s:Share {id:$i}) SET s.exp = 1", {"i": links[1]["id"]})
    assert (await client.get(links[1]["path"])).status_code == 404                              # expired
    assert (await client.get("/share/ps_notarealtoken")).status_code == 404 and (await client.get("/share/zzz")).status_code == 404
    listed = (await client.get(f"/v1/circles/{cid}/shares", headers=auth(other))).json()
    assert len(listed) == 3 and all("token" not in x and "hash" not in x for x in listed) and sum(x["active"] for x in listed) == 1


async def test_a_note_written_back_reaches_the_circle_labelled_unverified_and_the_page_escapes_everything(client):
    token, cid = await circle_with_medicines(client)
    await client.post(f"/v1/tenants/{cid}/care_record", headers=auth(token), json={"person": "asha", "drug": "<script>alert(1)</script>", "dose_text": "<img src=x onerror=alert(1)>", "source_type": "typed"})
    link = (await client.post(f"/v1/circles/{cid}/shares", headers=auth(token), json={"person": "asha"})).json()
    page = (await client.get(link["path"])).text
    assert "<script>alert(1)" not in page and "<img src=x" not in page                         # nothing a family typed becomes markup
    r = await client.post(f"/v1/share/{link['token']}/review", json={"name": "Dr. Rao (chemist)", "note": "Please ask the doctor about the pair."})
    assert r.status_code == 200, r.text
    assert (await client.post(f"/v1/share/{link['token']}/review", json={"name": "", "note": "x"})).status_code in (400, 422)
    got = (await client.post(f"/v1/tenants/{cid}/care_pharmacist_reviews", headers=auth(token), json={"person": "asha"})).json()["result"]
    assert got[0]["name"] == "Dr. Rao (chemist)" and got[0]["verified"] is False
    assert (await client.post("/v1/share/ps_nope/review", json={"name": "x", "note": ""})).status_code == 404
