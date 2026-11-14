# voice/ — owner: @voice

Done so far: `led_states.py` (LED vocabulary and `LedController`).

## 1. Baseline loop (build first)

Template: `vexo-open-kit/examples/python/voice_commands.py`. It already goes band mic →
Deepgram → a tool-calling model. Replace its OpenAI call with Gemini. Do not run the kit's
`ai.py` with anyone's personal OpenAI key.

One turn:

1. Double-tap on the band (`band_source.connect(..., on_double_tap=...)`).
2. Turn the mic on for `config.LISTEN_SECONDS`. The LED is locked solid blue meanwhile.
3. Send the audio to Deepgram for text. Turn the mic off.
4. Send the text to Gemini (`config.GEMINI_MODEL`, a Gemini 4 id) with `interfaces.TOOLS` as
   function declarations, plus `app.landmark_summary()` so it can use landmark ids. It must
   answer with a tool call.
5. Run it with `app.call_tool(name, args)`. That validates the arguments and returns a
   `ToolResult` with `say` and `led`.
6. Speak `say` with ElevenLabs (`config.ELEVENLABS_VOICE_ID`) on the laptop speaker. The
   LED state is applied by `app.output` once the mic is off.

Fallbacks: if Deepgram or Gemini fails, use `app.keyword_command(text)`. If ElevenLabs
fails, use the macOS `say` command or print.

Keys: call `keys.prepare()` once at start-up (before importing google-genai, Pipecat or the
kit's `speech`), then pass every key explicitly: `keys.get("gemini")`, `keys.get("deepgram")`,
`keys.get("elevenlabs")`. They read only `VEXO_GEMINI_API_KEY`, `VEXO_DEEPGRAM_API_KEY` and
`VEXO_ELEVENLABS_API_KEY`. Never let an SDK find a key by itself: generic names such as
`GEMINI_API_KEY` can be a teammate's personal, postpaid key. Never print them.
Tap-to-talk only: no always-on listening.

## 2. Pipecat port (needed for the Deepgram track)

Once the baseline works, on a branch: Deepgram STT service → Gemini LLM service with the
same tools → ElevenLabs TTS service → local audio out. Start with the laptop mic as input.
Then feed band audio: decode the band's Opus packets to 16 kHz PCM with the kit's decoder
(`vexo-open-kit/docs/speech.md`) and push them into the pipeline. Merge when one spoken turn
works end to end. If it is not working by about 15:30, ship the baseline.
