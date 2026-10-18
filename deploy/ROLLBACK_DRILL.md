# Rollback drill

What it is: `deploy/test_rollback.sh` builds a throwaway copy of the deploy situation and runs `deploy/rollback.sh` on it.

1. A git checkout with a compose file and a good version answering on a local port.
2. `.prev_deploy` is written with the good commit (the pipeline does this before every update).
3. A broken update is committed and started (its container exits at once); the script confirms the site is down.
4. `rollback.sh` runs. The test checks the code is back at the good commit and the old version answers.

Run it with `bash deploy/test_rollback.sh` (needs docker and git). CI runs it on every push. The first run of this drill found that the test did not pass the checkout directory to the script (`/opt/cc` was assumed); fixed in the test.
