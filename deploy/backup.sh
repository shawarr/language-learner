#!/usr/bin/env bash
# Consistent backup of the SQLite DB (WAL-safe) + gzip, keeping the last 30.
#
# Copying tutor.db with cp while the app is running can capture a torn database:
# recent writes live in the -wal file. The sqlite backup API takes a proper snapshot
# instead. We use python3 so the sqlite3(1) binary is not required on the host.
#
# Cron (daily 03:17):
#   17 3 * * * /opt/language-learner/deploy/backup.sh >> /var/log/tutor-backup.log 2>&1
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${DB:-$REPO/data/tutor.db}"
DEST="${DEST:-$REPO/backups}"
KEEP="${KEEP:-30}"

[ -f "$DB" ] || { echo "no database at $DB" >&2; exit 1; }
mkdir -p "$DEST"

STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="$DEST/tutor-$STAMP.db"

python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PY

gzip -f "$OUT"
echo "wrote $OUT.gz ($(du -h "$OUT.gz" | cut -f1))"

# Prune oldest beyond KEEP.
ls -1t "$DEST"/tutor-*.db.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
