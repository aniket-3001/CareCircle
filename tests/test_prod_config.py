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


def test_prod_compose_can_put_a_password_on_the_database_and_the_app_sends_it():
    prod = (ROOT / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "--requirepass" in prod and re.search(r"GRAPHMEM_DB_PASSWORD:\s*\$\{GRAPHMEM_DB_PASSWORD", prod) and "REDISCLI_AUTH" in prod   # the health check authenticates too
    for f in ("graphmem/db.py", "carecircle/checks.py", "carecircle/algos.py", "carecircle/reference.py", "carecircle/external.py"):
        assert "GRAPHMEM_DB_PASSWORD" in (ROOT / f).read_text(encoding="utf-8"), f           # every place that opens a connection


def test_prod_compose_has_no_append_only_log_memory_limits_and_rotating_logs():
    prod = (ROOT / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "--appendonly no" in prod and "--appendonly yes" not in prod and "--save 60 1" in prod          # the write log that crashed on replay stays off
    for svc in ("falkordb", "api", "caddy"):
        block = re.search(rf"\n  {svc}:\n(.*?)(?=\n  \w[\w-]*:\n|\nvolumes:)", prod, re.S).group(1)
        assert "mem_limit:" in block and "logging: *logging" in block, svc
    assert re.search(r'max-size: "10m", max-file: "3"', prod)


def test_a_deploy_takes_a_backup_before_it_touches_anything():
    wf = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    cmds = re.search(r"commands=\[(.*?)\]'", wf, re.S).group(1)
    assert cmds.index("deploy/backup.sh") < cmds.index("git reset") < cmds.index("deploy/render_env.sh") < cmds.index("up -d --build")


def test_the_env_file_is_rendered_from_parameter_store_and_never_replaced_by_something_incomplete():
    sh = (ROOT / "deploy/render_env.sh").read_text(encoding="utf-8")
    assert "get-parameters-by-path" in sh and "--with-decryption" in sh and "keeping" in sh            # a store outage keeps the file on disk
    assert re.search(r"REQUIRED=.*GRAPHMEM_ADMIN_KEY.*GRAPHMEM_RO_PASSWORD", sh) and "install -m 600" in sh
    assert "\r" not in sh                                                                               # a shell script with Windows line endings does not run on the server
