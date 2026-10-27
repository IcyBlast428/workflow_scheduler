#!/usr/bin/env bash
# Prepare an immutable platform release, then activate it in a stopped maintenance window.
set -euo pipefail
MODE=deploy
if [[ "${1:-}" == --prepare || "${1:-}" == --activate ]]; then MODE="${1#--}"; shift; fi
REF="${1:?Usage: sudo bash scripts/deploy_release.sh [--prepare|--activate] <commit-or-ref> [deployment-root]}"
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
BASE="$(realpath -m "${2:-/data/wfs}")"
[[ "$BASE" != / && "$BASE" != "$SOURCE_ROOT" && "$BASE" != "$SOURCE_ROOT/"* && "$SOURCE_ROOT" != "$BASE/"* ]] || { echo 'Deployment root must be separate from the source checkout.' >&2; exit 2; }
[[ $EUID == 0 ]] || { echo 'Run as root to switch and restart systemd services.' >&2; exit 2; }
CONFIG="${WFS_DEPLOY_CONFIG:-/etc/wfs/wfs.env}"
PYTHON="${WFS_DEPLOY_PYTHON:-python3.12}"
WEB_PORT="${WFS_DEPLOY_WEB_PORT:-8008}"
CONTROL_PORT="${WFS_DEPLOY_CONTROL_PORT:-8009}"
[[ "$WEB_PORT" =~ ^[0-9]+$ && "$CONTROL_PORT" =~ ^[0-9]+$ ]] || { echo 'Invalid service ports.' >&2; exit 2; }
(( 10#$WEB_PORT >= 1 && 10#$WEB_PORT <= 65535 && 10#$CONTROL_PORT >= 1 && 10#$CONTROL_PORT <= 65535 && 10#$WEB_PORT != 10#$CONTROL_PORT )) || { echo 'Invalid service ports.' >&2; exit 2; }
[[ "$CONFIG" == /* && -r "$CONFIG" ]] || { echo 'An absolute, readable WFS_DEPLOY_CONFIG is required.' >&2; exit 2; }
id wfs >/dev/null
SHA="$(git -C "$SOURCE_ROOT" rev-parse --verify "${REF}^{commit}")"
[[ "$SHA" =~ ^[a-f0-9]{40}$ || "$SHA" =~ ^[a-f0-9]{64}$ ]] || exit 2
mkdir -p "$BASE"
exec 9>"$BASE/.deploy.lock"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 2; }
RELEASE="$BASE/releases/$SHA"
if [[ -e "$BASE/current" && ! -L "$BASE/current" ]]; then
  echo "$BASE/current must be a symlink; back up and migrate the existing directory first." >&2
  exit 2
fi
if [[ "$MODE" != activate ]]; then
  [[ ! -e "$RELEASE" ]] || { echo 'Release already exists; use --activate for a prepared release or inspect failed material.' >&2; exit 2; }
  [[ "$("$PYTHON" -c 'import sys; print("%s.%s" % sys.version_info[:2])')" == 3.12 ]] || { echo 'Use Python 3.12 for the committed production dependency lock.' >&2; exit 2; }
  mkdir -p "$RELEASE"
  git -C "$SOURCE_ROOT" archive "$SHA" | tar -x -C "$RELEASE"
  printf '%s\n' "$SHA" > "$RELEASE/.release-revision"
  cd "$RELEASE"
  "$PYTHON" -m venv .venv
  pip_options=()
  if [[ -n "${WFS_DEPLOY_WHEELHOUSE:-}" ]]; then pip_options=(--no-index --find-links "$WFS_DEPLOY_WHEELHOUSE"); fi
  .venv/bin/python -m pip install "${pip_options[@]}" -r requirements-linux-py312.lock
  .venv/bin/python -m pip check
  env WFS_TEST_GAUSS=false WFS_TEST_MYSQL=false .venv/bin/python -m unittest discover -s tests -v
  npm --prefix frontend ci --no-audit --no-fund
  npm --prefix frontend test
  npm --prefix frontend run build
  # Driver configuration is release-local and remains valid after a rollback.
  .venv/bin/python -c 'from pathlib import Path; import sys; p=Path("app/config/driver/dws_odbc/etc/odbcinst.ini"); p.write_text(p.read_text().replace("/data/wfs/current",sys.argv[1]))' "$RELEASE"
  printf '%s\n' "$SHA" > "$RELEASE/.release-ready.pending"
  chown -R root:wfs "$RELEASE"
  chmod -R g-w,o-rwx "$RELEASE"
  mv "$RELEASE/.release-ready.pending" "$RELEASE/.release-ready"
  if [[ "$MODE" == prepare ]]; then
    echo "Prepared $SHA; services and production database were not changed."
    exit 0
  fi
fi
[[ -f "$RELEASE/.release-ready" && "$(cat "$RELEASE/.release-ready")" == "$SHA" && "$(cat "$RELEASE/.release-revision")" == "$SHA" ]] || { echo 'Release is not a completed, matching prepared build.' >&2; exit 2; }
for unit in wfs.service wfs-scheduler.service; do
  [[ "$(systemctl show --property=LoadState --value "$unit")" == loaded ]] || { echo 'Install both systemd units before activation.' >&2; exit 2; }
  active_state="$(systemctl show --property=ActiveState --value "$unit")"
  if [[ "$active_state" != inactive && "$active_state" != failed ]]; then
    echo 'Activation requires a stopped maintenance window: drain tasks, stop both services, and back up database/shared data first.' >&2
    exit 2
  fi
done
mkdir -p "$BASE/shared/logs" "$BASE/shared/data"
if [[ -L "$BASE/current" && -d "$BASE/current/data" && -n "$(find "$BASE/current/data" -mindepth 1 -print -quit)" && -z "$(find "$BASE/shared/data" -mindepth 1 -print -quit)" ]]; then
  echo 'Existing current/data needs an offline backup and migration to shared/data.' >&2
  exit 2
fi
cd "$RELEASE"
maintenance=(.venv/bin/python scripts/service_config.py --environment-file "$CONFIG" --data "$BASE/shared/data" --logs "$BASE/shared/logs" --)
# These steps occur only after both services have stopped. Migrations are never
# rolled back automatically; release migrations must remain backward compatible.
"${maintenance[@]}" "$RELEASE/.venv/bin/python" scripts/migrate.py
"${maintenance[@]}" "$RELEASE/.venv/bin/python" scripts/migrate_legacy_tasks.py --verify-only
chown -R wfs:wfs "$BASE/shared/logs" "$BASE/shared/data"
previous=''
if [[ -L "$BASE/current" ]]; then previous="$(readlink -f "$BASE/current")"; fi
activate() {
  ln -s "$1" "$BASE/.current-$$"
  mv -Tf "$BASE/.current-$$" "$BASE/current"
}
recover() {
  trap - ERR
  systemctl stop wfs.service wfs-scheduler.service || true
  if [[ -n "$previous" ]]; then
    activate "$previous"
    systemctl start wfs-scheduler.service wfs.service || true
    echo "Activation failed; restored previous code $previous. Database changes were not undone; verify recovery." >&2
  else
    echo 'First activation failed; services stopped, release and data retained for diagnosis.' >&2
  fi
}
trap recover ERR
activate "$RELEASE"
systemctl start wfs-scheduler.service wfs.service
ready=false
for _ in {1..30}; do
  if curl --max-time 6 --fail --silent "http://127.0.0.1:$CONTROL_PORT/api/user/ready" >/dev/null &&
     curl --max-time 6 --fail --silent "http://127.0.0.1:$WEB_PORT/api/user/ready" >/dev/null; then ready=true; break; fi
  sleep 1
done
[[ "$ready" == true ]]
trap - ERR
echo "Activated $SHA using systemd; business task versions and outputs are unchanged."
