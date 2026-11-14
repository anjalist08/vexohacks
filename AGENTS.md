# Rules for AI agents (Antigravity /swarm, Agent Manager, Claude, anyone)

Read these first, in order:

1. This file.
2. `VexoHacks_Plan_Wearable_Spatial_Memory.md`: the build plan, including the amendments
   (sponsor tracks, Pipecat, tracking fixes).
3. `vexo-open-kit/AGENTS.md`: the band's own rules. They override anything here.

## Hard rules

- **Never connect to a band.** Not the real one, and not the kit's pretend band either:
  the kit forbids running with any number but the team's, and `config.BAND` stays the
  team's to set. Build and test against `python3 main.py --sim` and the unit tests, which
  use synthetic walks and need no band. A person runs the real band from their own Terminal.
- **Never read, print, log or commit `.env` or any key.** Keys are read from the environment
  at runtime only. Before every push, check that `git status` does not list `.env`.
- **Only the `VEXO_` key names, only through `keys.py`.** Call `keys.prepare()` at start-up and
  pass keys explicitly. Never read `GEMINI_API_KEY`, `GOOGLE_API_KEY` or `OPENAI_API_KEY`, and
  never let an SDK pick a key up by itself: those names can hold a teammate's personal key.
- **Never send a key to the browser page.** Deepgram, Gemini and ElevenLabs are called from
  Python only.
- **Stay in your folder.** Each worker edits only the folders it owns (below).
- **Shared files need the board.** `interfaces.py` and `config.py` are shared. Do not change
  a field, a tool or a name in them without posting on the board and getting an OK.
- **Commit small and often**, on your own branch, and merge to `main` before you are removed.
  Every commit ends with these two lines:

      Co-Authored-By: anjalist08 <anjalist08@gmail.com>
      Co-Authored-By: <your model name> <its noreply address>

- **The model never computes positions.** Gemini picks the tool and matches names. Code in
  `store/` computes every coordinate, distance and turn.
- **Never present a replay or the synthetic walk as live sensing**, and never quote an
  accuracy number that a real walk did not measure.
- Python 3.9: no `X | Y` type unions, no `match`.

## Who owns what

| Worker | Owns | Builds next |
| --- | --- | --- |
| `@tracker` | `tracker/` | Tune on real logged walks in `data/logs/` (step length, turn threshold, settle time), heading-uncertainty signal for the red LED state, live position feed |
| `@memory` | `store/`, `web/`, `app.py` | Map page with live trace and landmarks over a websocket (see `web/README.md`), step-by-step guidance that advances as the user walks, landmarks mirrored to band storage (P2) |
| `@voice` | `voice/` | Tap-to-talk loop: double-tap → mic → Deepgram → Gemini tool call → `app.call_tool` → ElevenLabs → LED. Then the Pipecat port (see `voice/README.md`) |

## How to verify

    python3 -m unittest          # all tests pass
    python3 main.py --sim        # the scripted demo runs end to end

Add tests for what you build. A worker is done when both commands pass on `main`
after its merge.
