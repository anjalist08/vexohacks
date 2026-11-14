# web/ — Live 2D Metric Map & WebSocket Bridge (`@memory`)

Live browser dashboard displaying the recorded indoor walk (`+x` right, `+y` up, in metres), saved landmarks, current walker pose & heading, wrist LED cue, band link status, and step-by-step advancing return guidance.

## Quick start (one-command preview)

From the project root:

```bash
# Synthetic walk + return guidance demo (explicitly labelled SIMULATION):
python3 -m web.ws_server --sim

# Or replay a logged walk CSV (explicitly labelled REPLAY):
python3 -m web.ws_server --replay data/logs/walk.csv
```

Then open <http://localhost:8000/web/> in Chrome, Safari, Firefox, or Edge.

If you are already serving static files separately (`python3 -m http.server 8000 --bind 127.0.0.1`), pass `--no-http` to `web.ws_server`. To connect the page to a custom WebSocket port, append `?ws=ws://127.0.0.1:PORT`.

## WebSocket protocol (`127.0.0.1:8765`)

Server-to-browser JSON messages:
- `{"type": "mode", "mode": "LIVE|SIMULATION|REPLAY"}`
- `{"type": "link", "status": "connected|reconnecting|reconnected|simulated|replay"}`
- `{"type": "led", "state": "...", "period": 280}`
- `{"type": "point", "t": ..., "x_m": ..., "y_m": ..., "heading_deg": ..., "steps": ...}`
- `{"type": "landmark", "id": "...", "label": "...", "point_index": ..., "floor": ..., "note": ..., "x_m": ..., "y_m": ...}`
- `{"type": "guidance", "instructions": [...], "current_index": ..., "active": ..., "waypoints": [...]}`
- `{"type": "say", "text": "..."}`
- `{"type": "reset"}`

Browser-to-server JSON command messages:
- `{"type": "command", "text": "start route"}` (dispatched via `app.keyword_command`, or `app.delete_all()` for `"delete all"`).

## Safety & privacy
- Always binds to `127.0.0.1` by default; dotfiles (`.env`, `.git`) are blocked with HTTP `403`.
- No API key ever reaches `web/`.
- All dynamic text is rendered strictly with `textContent` and DOM nodes.
- Non-live runs display a prominent `SIMULATION` or `REPLAY` banner.
