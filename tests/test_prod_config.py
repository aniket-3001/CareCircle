"""What production runs must be what the README says: reads go through the read-only database user, and the speech model is the one baked into the image."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_prod_compose_turns_on_the_read_only_database_user_and_names_the_baked_speech_model():
    prod = (ROOT / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
    assert re.search(r"GRAPHMEM_RO_PASSWORD:\s*\$\{GRAPHMEM_RO_PASSWORD:\?", prod), "the read-only user must be required, not optional"
    baked = re.search(r"WhisperModel\('(\w+)'", (ROOT / "Dockerfile").read_text(encoding="utf-8")).group(1)
    assert re.search(rf"CC_WHISPER:\s*{baked}\b", prod)
    assert f'"CC_WHISPER", "{baked}"' in (ROOT / "carecircle/intake.py").read_text(encoding="utf-8")        # the code default agrees with the image too
