"""A grant is looked up once a second at most; a change made through this process takes effect at once."""
import pytest

from conftest import tid
from graphmem.policy import PermissionDenied


async def test_a_revoke_is_felt_at_once_and_repeated_checks_do_not_each_ask_the_database(gm):
    t = tid(gm, "gc")
    await gm.grant("ann", t, ("read", "write"))
    m = gm.open("ann", t)
    await m.care_record("asha", "metformin", dose_text="500 mg")
    asked = []
    real = gm._ctl

    async def spy():
        asked.append(1)
        return await real()
    gm._ctl = spy
    try:
        for _ in range(5):
            await m.care_regimen("asha")
        assert len(asked) <= 1, f"{len(asked)} control-graph lookups for 5 reads"        # one lookup, then the cached grant
        await gm.revoke("ann", t)
        with pytest.raises(PermissionDenied):
            await m.care_regimen("asha")                                                  # no waiting for the cache to expire
        await gm.grant("ann", t, ("read",))
        await m.care_regimen("asha")
        with pytest.raises(PermissionDenied):
            await m.care_record("asha", "warfarin", dose_text="5 mg")                      # a downgrade is felt at once too
    finally:
        gm._ctl = real
