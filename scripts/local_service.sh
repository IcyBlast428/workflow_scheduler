#!/usr/bin/env bash
# Manage the installed local Web and Scheduler services.
set -euo pipefail
case "${1:-status}" in
 start) systemctl --user start wfs-local-scheduler.service wfs-local.service ;;
 stop) systemctl --user stop wfs-local.service wfs-local-scheduler.service ;;
 restart) systemctl --user restart wfs-local-scheduler.service wfs-local.service ;;
 status) systemctl --user status wfs-local.service wfs-local-scheduler.service ;;
 *) echo 'Usage: local_service.sh [start|stop|restart|status]' >&2; exit 2 ;;
esac
