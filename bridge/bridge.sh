#!/bin/bash
# Control script for the Whiteboard Bridge HTTP server.
# Usage: bridge.sh {start|stop|restart|status}

cd "$(dirname "$0")"

PID_FILE="bridge.pid"
LOG_FILE="bridge.log"

is_alive() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

cmd_start() {
  if is_alive; then
    echo "Already running (PID $(cat "$PID_FILE"))"
    exit 1
  fi
  rm -f "$PID_FILE"
  nohup python3 server.py >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 0.5
  if ! is_alive; then
    echo "Server failed to start. See bridge/$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
  fi
  echo "Started (PID $(cat "$PID_FILE"), http://localhost:8767)"
}

cmd_stop() {
  if ! is_alive; then
    echo "Not running"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid=$(cat "$PID_FILE")
  kill -TERM "$pid" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null
  fi
  rm -f "$PID_FILE"
  echo "Stopped"
}

cmd_status() {
  if is_alive; then
    echo "Running (PID $(cat "$PID_FILE"))"
  elif [[ -f "$PID_FILE" ]]; then
    echo "Stale PID file at bridge/$PID_FILE (process gone); run '$0 start' to clean up"
  else
    echo "Stopped"
  fi
}

case "$1" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop && cmd_start ;;
  status)  cmd_status ;;
  ""|--help|-h)
    cat <<EOF
Usage: bridge.sh {start|stop|restart|status}
  start    run server in background, log to bridge.log
  stop     terminate running server (TERM, then KILL after 5s)
  restart  stop then start
  status   show running PID or stopped state
EOF
    [[ -z "$1" ]] && exit 1 || exit 0
    ;;
  *)
    echo "Unknown command: $1" >&2
    echo "Usage: bridge.sh {start|stop|restart|status}" >&2
    exit 1
    ;;
esac
