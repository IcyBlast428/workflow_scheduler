#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
ENV_FILE="${2:-.env.local}"
if [[ "$ENV_FILE" != .env.local && "$ENV_FILE" != .env.postgres.local ]]; then
  echo '请选择 .env.local 或 .env.postgres.local。' >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "配置缺失：$ENV_FILE。请先运行对应的本地环境初始化脚本。" >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a
if [[ "${WFS_ENV:-}" != development ]]; then
  echo '本脚本只用于独立的本地开发数据库。' >&2
  exit 1
fi
if [[ -z "${WFS_LOCAL_DB_PATH:-}" && ( "${WFS_POSTGRES_TEST:-}" != true || "${WFS_DB_ID:-}" != wfstest_wfs || "${WFS_DB_DRIVER:-}" != 'PostgreSQL Unicode' ) ]]; then
  echo '本脚本只允许独立 SQLite 或指定的 PostgreSQL 测试库。' >&2
  exit 1
fi
PYTHON_BIN="${WFS_PYTHON:-python3}"
PORT="${WFS_PORT:-18008}"
CONTROL_PORT="${WFS_CONTROL_PORT:-18009}"
mkdir -p "$ROOT/data"
exec 9>"$ROOT/data/.service.lock"
flock -n 9 || { echo 'Another service operation is running.' >&2; exit 2; }

is_ours() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null &&
    [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" == "$ROOT" ]] &&
    [[ "$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)" == *gunicorn* ]]
}

stop_services() {
  local name pid
  for name in web scheduler; do
    [[ -f "$ROOT/data/$name.pid" ]] || continue
    read -r pid < "$ROOT/data/$name.pid"
    if is_ours "$pid"; then
      kill -TERM "$pid"
      for _ in {1..20}; do
        is_ours "$pid" || break
        sleep 0.5
      done
      if is_ours "$pid"; then kill -KILL -- "-$pid"; fi
    fi
    rm -f -- "$ROOT/data/$name.pid"
  done
}

case "${1:-status}" in
  start)
    active=0
    for name in scheduler web; do
      if [[ -f "data/$name.pid" ]]; then
        read -r pid < "data/$name.pid"
        if is_ours "$pid"; then
          active=$((active + 1))
        fi
      fi
    done
    if [[ "$active" == 2 ]]; then
      echo "已有实例运行；访问 http://127.0.0.1:$PORT/"
      exit 0
    fi
    if [[ "$active" != 0 ]]; then stop_services; fi
    trap stop_services ERR
    nohup setsid env WFS_ENABLE_SCHEDULER=true WFS_SCHEDULER_CONTROL_URL= \
      "$PYTHON_BIN" -m gunicorn -c gunicorn.conf.py --workers 1 --worker-class gthread --threads 8 \
      --timeout 60 --graceful-timeout 15 --bind "127.0.0.1:$CONTROL_PORT" run:app \
      >"$ROOT/data/scheduler.log" 2>&1 </dev/null 9>&- &
    echo "$!" > data/scheduler.pid
    nohup setsid env WFS_ENABLE_SCHEDULER=false WFS_SCHEDULER_CONTROL_URL="http://127.0.0.1:$CONTROL_PORT" \
      "$PYTHON_BIN" -m gunicorn -c gunicorn.conf.py --workers 2 --worker-class gthread --threads 8 \
      --timeout 60 --graceful-timeout 15 --bind "127.0.0.1:$PORT" run:app \
      >"$ROOT/data/web.log" 2>&1 </dev/null 9>&- &
    echo "$!" > data/web.pid
    ready=false
    for _ in {1..30}; do
      if curl --max-time 6 --silent --fail "http://127.0.0.1:$CONTROL_PORT/api/user/ready" >/dev/null &&
         curl --max-time 6 --silent --fail "http://127.0.0.1:$PORT/api/user/ready" >/dev/null; then
        ready=true
        break
      fi
      sleep 0.5
    done
    if [[ "$ready" != true ]]; then
      tail -n 25 data/scheduler.log data/web.log >&2
      stop_services
      exit 1
    fi
    for name in scheduler web; do
      read -r pid < "data/$name.pid"
      is_ours "$pid" || { stop_services; exit 1; }
    done
    trap - ERR
    echo "WSL 服务已启动：http://127.0.0.1:$PORT/"
    ;;
  stop) stop_services; echo 'WSL 本地服务已停止。' ;;
  status)
    for name in scheduler web; do
      pid=''
      [[ ! -f "data/$name.pid" ]] || read -r pid < "data/$name.pid"
      if is_ours "$pid"; then echo "$name: running ($pid)"; else echo "$name: stopped"; fi
    done
    ;;
  *) echo 'Usage: bash scripts/local_service.sh [start|stop|status] [.env.local|.env.postgres.local]' >&2; exit 2 ;;
esac
