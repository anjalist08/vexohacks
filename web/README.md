# web/ — owner: @memory

Not built yet: the map page that shows the live trace on the laptop.

- Python pushes JSON to the page over a websocket. The kit has a small server to start from:
  `vexo-open-kit/examples/python/tiny_websocket.py`.
- Messages: `{"type": "point", ...PoseSample}` for each new route point,
  `{"type": "landmark", ...Landmark}`, `{"type": "guidance", "instructions": [...]}`,
  `{"type": "led", "state": "..."}`, and `{"type": "link", "status": "connected|reconnecting|reconnected"}`.
- Draw the trace (x right, y up, metres), the landmarks with labels, the current position
  and heading, the LED state, and the link status. Label it "REPLAY" or "SIMULATION" when
  it is not live.
- A text box sends typed commands back; Python runs them with `app.keyword_command`.
- No API key ever reaches this page.
- Serve it with `python3 -m http.server 8000 --bind 127.0.0.1`.
