"""Voice subsystem: LED cues, Gemini tool router, ElevenLabs TTS, and tap-to-talk loop."""
from voice.elevenlabs_tts import ElevenLabsError, ElevenLabsSpeaker, speak, synthesize_mp3
from voice.gemini_client import (
    GeminiError,
    build_function_declarations,
    build_request_payload,
    build_system_instruction,
    choose_tool,
)
from voice.led_states import STATES, LedController, LedCue, turn_now_period
from voice.loop import VoiceLoop

__all__ = [
    "ElevenLabsError",
    "ElevenLabsSpeaker",
    "GeminiError",
    "LedController",
    "LedCue",
    "STATES",
    "VoiceLoop",
    "build_function_declarations",
    "build_request_payload",
    "build_system_instruction",
    "choose_tool",
    "speak",
    "synthesize_mp3",
    "turn_now_period",
]
