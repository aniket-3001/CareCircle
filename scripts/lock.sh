#!/bin/bash
# Regenerate the hash-locked install files for the image and CI (Linux, Python 3.12, the platform they run on, not this machine):
#   requirements.lock     from requirements.txt                              (the Docker image)
#   requirements-ci.lock  from requirements.txt + requirements-integrations.txt  (CI and the compat job)
# Every package, direct or not, is pinned with the SHA-256 of its files, and pip refuses anything that does not match (--require-hashes).
# Slow (it hashes every wheel; about half an hour). Run the whole suite after a regeneration: CI runs on exactly these files.
set -euo pipefail
cd "$(dirname "$0")/.."
FLAGS="--generate-hashes --allow-unsafe --strip-extras --no-header --annotation-style=line"
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/w" -w /w python:3.12-slim sh -c "pip install -q pip-tools && \
  pip-compile -q $FLAGS requirements.txt -o requirements.lock && \
  pip-compile -q $FLAGS requirements.txt requirements-integrations.txt -o requirements-ci.lock"
