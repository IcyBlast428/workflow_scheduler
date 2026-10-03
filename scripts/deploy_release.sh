#!/usr/bin/env bash
# Build a complete release before switching the service's current symlink.
set -euo pipefail
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
REF="${1:?Usage: sudo bash scripts/deploy_release.sh <commit-or-ref> [deployment-root]}"
BASE="${2:-/data/wfs}"
BASE="$(realpath -m "$BASE")"
[[ "$BASE" != / && "$BASE" != "$SOURCE_ROOT" ]] || { echo 'Deployment root must be separate from the source checkout.' >&2; exit 2; }
[[ $EUID == 0 ]] || { echo 'Run as root to switch and restart systemd services.' >&2; exit 2; }
id wfs >/dev/null
[[ -r /etc/wfs/wfs.env ]] || { echo '/etc/wfs/wfs.env is required.' >&2; exit 2; }
SHA="$(git -C "$SOURCE_ROOT" rev-parse --verify "${REF}^{commit}")"
mkdir -p "$BASE"
exec 9>"$BASE/.deploy.lock"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 2; }
RELEASE="$BASE/releases/$SHA"
[[ ! -e "$RELEASE" ]] || { echo "Release already exists: $RELEASE" >&2; exit 2; }
mkdir -p "$RELEASE" "$BASE/shared/logs" "$BASE/shared/data"
if [[ -L "$BASE/current" && -d "$BASE/current/data" && -n "$(find "$BASE/current/data" -mindepth 1 -print -quit)" && -z "$(find "$BASE/shared/data" -mindepth 1 -print -quit)" ]]; then
  echo 'Existing task data needs migration: stop services, back up and copy current/data into shared/data before deploying.' >&2
  exit 2
fi
git -C "$SOURCE_ROOT" archive "$SHA" | tar -x -C "$RELEASE"
printf '%s\n' "$SHA" > "$RELEASE/.release-revision"
cd "$RELEASE"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux-py312.lock
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
# Build declared per-task and per-group environments inside this release.
while IFS= read -r requirements; do
  task_directory="$(dirname "$requirements")"
  python3 -m venv "$task_directory/.venv"
  "$task_directory/.venv/bin/python" -m pip install -r "$requirements"
done < <(find app/jobs -mindepth 2 -maxdepth 3 -name requirements.txt -type f)
set -a
source /etc/wfs/wfs.env
set +a
unset WFS_LOCAL_DB_PATH
export WFS_ENV=production
export WFS_LOG_DIR="$BASE/shared/logs"
export WFS_DATA_DIR="$BASE/shared/data"
export ODBCSYSINI="$RELEASE/app/config/driver/dws_odbc/etc"
export ODBCINI="$ODBCSYSINI/odbc.ini"
sed -i "s|/data/wfs/current|$RELEASE|g" "$ODBCSYSINI/odbcinst.ini"
.venv/bin/python scripts/migrate.py
chown -R root:wfs "$RELEASE"
chmod -R g-w,o-rwx "$RELEASE"
chown -R wfs:wfs "$BASE/shared/logs" "$BASE/shared/data"
previous=''
if [[ -L "$BASE/current" ]]; then previous="$(readlink -f "$BASE/current")"; fi
if [[ -e "$BASE/current" && ! -L "$BASE/current" ]]; then
  echo "$BASE/current must be a symlink; preserve the existing directory before migration." >&2
  exit 2
fi
activate() {
  ln -s "$1" "$BASE/.current-$$"
  mv -Tf "$BASE/.current-$$" "$BASE/current"
}
recover() {
  if [[ -n "$previous" ]]; then
    activate "$previous"
    systemctl restart wfs-scheduler wfs
    echo "Activation failed; restored $previous" >&2
  else
    systemctl stop wfs wfs-scheduler || true
    echo 'Activation failed; release retained for diagnosis.' >&2
  fi
}
activate "$RELEASE"
trap recover ERR
systemctl restart wfs-scheduler wfs
ready=false
for _ in {1..30}; do
  if curl --max-time 6 --fail --silent "http://127.0.0.1:8009/api/user/ready" >/dev/null &&
     curl --max-time 6 --fail --silent "http://127.0.0.1:8008/api/user/ready" >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]]
trap - ERR
echo "Activated $SHA"
