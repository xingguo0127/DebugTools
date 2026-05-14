# Bridge Control Script

**Date:** 2026-05-14
**Status:** Design approved

## Goal

Add a `bridge.sh` control script that runs the Python HTTP bridge as a background daemon, with `start | stop | restart | status` subcommands. Eliminate the need for manual `cd bridge && python server.py &` and `pkill -f` invocations.

## Non-goals

- Auto-start at login (no launchd plist).
- Log rotation (user clears `bridge.log` manually if it grows).
- Foreground mode — daemon only.
- Port configuration (8767 stays hard-coded in `server.py`).
- Multi-instance (single PID file, single port).

## File layout

```
bridge/
  bridge.sh       (new — control script, chmod +x, committed)
  bridge.pid      (runtime — created by start, deleted by stop, gitignored)
  bridge.log      (runtime — appended on each start, gitignored)
  server.py       (unchanged)
  test_device_parsers.py
```

Repo root gains a `.gitignore` covering both runtime artifacts and existing untracked dirs.

## Commands

### `start`

1. Read `bridge.pid`. If it exists and `kill -0 $PID` succeeds (process alive) → print `Already running (PID $PID)` and exit 1.
2. If `bridge.pid` exists but the process is dead, treat as stale: remove it and continue.
3. Launch: `nohup python3 server.py >> bridge.log 2>&1 &`.
4. Write the new PID to `bridge.pid`.
5. Sleep 0.5s.
6. Re-check `kill -0 $PID`. If dead → print `Server failed to start. See bridge/bridge.log` and exit 1.
7. Otherwise print `Started (PID $PID, http://localhost:8767)` and exit 0.

### `stop`

1. If `bridge.pid` missing or its process is already dead → print `Not running` and exit 0 (noop, not an error).
2. Send SIGTERM. Wait up to 5 seconds, polling `kill -0 $PID` every 0.5s.
3. If still alive after the wait, send SIGKILL.
4. Remove `bridge.pid`.
5. Print `Stopped`.

### `restart`

`stop` then `start`. Exit code reflects the `start` result (so a failed restart fails loudly).

### `status`

- PID file exists and process alive → `Running (PID $PID)`, exit 0.
- PID file missing → `Stopped`, exit 0.
- PID file exists but process dead → `Stale PID file at bridge/bridge.pid (process gone); run 'bridge.sh start' to clean up`, exit 0.

### No argument or `--help`

Print:
```
Usage: bridge.sh {start|stop|restart|status}
  start    — run server in background, log to bridge.log
  stop     — terminate running server (TERM, then KILL after 5s)
  restart  — stop then start
  status   — show running PID or stopped state
```

Exit 0 on `--help`, exit 1 on unknown argument.

## Implementation notes

- Set `cd "$(dirname "$0")"` at the top so the script works regardless of caller's CWD. All paths (`bridge.pid`, `bridge.log`, `server.py`) are relative to script location after that.
- Use `python3` explicitly (avoid macOS legacy `python` → Python 2).
- Use `kill -0 $PID` (POSIX, doesn't send a signal — just probes existence).
- Use bash `#!/bin/bash`, not `/bin/sh` (relies on `[[`/arithmetic constructs).
- Log mode is append (`>>`), not truncate. Preserves history across restarts.
- The script does NOT detect port conflicts directly. If 8767 is taken, Python raises `OSError: [Errno 48]` and the process dies within ~0.5s — caught by step 6 of `start`, which directs the user to `bridge.log`.

## `.gitignore`

Add `.gitignore` at repo root:

```
bridge/__pycache__/
bridge/images/
bridge/exports/
bridge/bridge.pid
bridge/bridge.log
```

`bridge/images/` and `bridge/exports/` are pre-existing untracked dirs from prior runtime use; ignoring them silences `git status` noise.

## Error handling

| Case | Behavior |
|---|---|
| `start` while already running | Exit 1, message names the live PID |
| `start` with stale PID file | Silently clean up and start fresh |
| `start` but server crashes <0.5s | Exit 1, point user to log |
| `stop` when not running | Exit 0, print "Not running" (idempotent) |
| `stop` when process won't die | After 5s SIGTERM, escalate to SIGKILL |
| Unknown subcommand | Exit 1, print usage |

## Testing

Manual smoke tests (no automated tests — pure shell wrapper):

- [ ] `./bridge.sh start` from repo root and from inside `bridge/` both work
- [ ] `./bridge.sh status` shows PID after start
- [ ] `curl http://localhost:8767/api/devices` works after start
- [ ] `./bridge.sh start` again refuses with "Already running"
- [ ] `./bridge.sh stop` terminates cleanly, status now shows Stopped
- [ ] `./bridge.sh stop` again is a noop
- [ ] `./bridge.sh restart` cycles cleanly
- [ ] Manually `kill -9` the server, then `./bridge.sh status` reports stale PID
- [ ] `./bridge.sh start` after a stale-PID state recovers without manual cleanup
- [ ] Force port collision: run server.py manually, then `./bridge.sh start` — should fail within 1s with log pointer

## Out of scope / future

- `bridge.sh logs` (tail wrapper)
- launchd plist for boot-time start
- Log rotation
