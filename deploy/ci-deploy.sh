#!/usr/bin/env bash
# What the CI deploy key is allowed to run, and nothing else (forced command in authorized_keys).
#
# Pulls main, backs up the database, builds and restarts. One deploy at a time. Refuses to deploy
# if the server's checkout has diverged from GitHub (someone edited files on the server) rather
# than overwriting the change; fix that by hand and push again.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
LOG=/var/log/tutor-deploy.log
exec > >(tee -a "$LOG") 2>&1

# The client may only say "deploy <sha>"; anything else is refused.
req="${SSH_ORIGINAL_COMMAND:-deploy}"
want=""
case "$req" in
  deploy) ;;
  "deploy "*) want="${req#deploy }" ;;
  *) echo "refused: $req"; exit 2 ;;
esac
[[ -z "$want" || "$want" =~ ^[0-9a-f]{7,40}$ ]] || { echo "refused: bad sha"; exit 2; }

exec 9>/var/lock/tutor-deploy.lock
flock -w 900 9 || { echo "another deploy is still running"; exit 1; }

echo "== $(date -Is) deploy requested ${want:-(latest)}"
git fetch --quiet origin main
if ! git merge --ff-only --quiet origin/main; then
  echo "the checkout here has diverged from origin/main; not overwriting it" >&2
  git status --short >&2
  exit 1
fi
head="$(git rev-parse HEAD)"
if [ -n "$want" ] && ! git merge-base --is-ancestor "$want" "$head"; then
  echo "requested $want is not in main here ($head); refusing" >&2
  exit 1
fi
echo "at $head: $(git log -1 --format=%s)"

# A copy of the database before every deploy: a migration that goes wrong costs one restore.
if [ -f data/tutor.db ]; then bash deploy/backup.sh; fi

bash deploy/deploy.sh
echo "== $(date -Is) deployed $head"
