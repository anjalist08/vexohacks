"""Every tunable value in one place. Only one person edits this file (see AGENTS.md).

Values marked PLACEHOLDER are guesses until the Gate B walk test measures them.
Do not quote accuracy numbers from them.
"""

# --- Band -------------------------------------------------------------------
# The number on your band's bag (the band is called Vexo-HACK-NN).
# Nothing connects to a band, real or pretend, until this is set.
# Never use 42 or any other number from the kit's examples.
BAND = 80                     # Vexo-HACK-80, the team's band (from the bag)

# --- Path tracking ------------------------------------------------------------
STEP_LENGTH_M = 0.70          # PLACEHOLDER: walk a measured distance, divide by steps
MOTION_RATE_HZ = 25           # motion samples a second (10, 25, 50, 100)
ACTIVITY_RATE = "fastest"     # step readings up to 10 a second on firmware 1.1
GRAVITY_ALPHA = 0.05          # low-pass weight for the gravity estimate (0..1)
CALIBRATION_S = 2.0           # stand still this long after "start route" to measure gyro bias

SNAP_TURNS = True             # round settled turns to multiples of 90 degrees (off outdoors)
TURN_RATE_DPS = 25.0          # PLACEHOLDER: yaw rate above this counts as turning
TURN_SETTLE_S = 0.6           # PLACEHOLDER: quiet time before a turn counts as finished
MIN_TURN_DEG = 45.0           # PLACEHOLDER: net turns smaller than this are ignored

BIAS_UPDATE_ALPHA = 0.02      # how fast still periods re-estimate the gyro bias
STILL_GYRO_DPS = 3.0          # gyro magnitude below this (with state "still") counts as still

# --- Return guidance ----------------------------------------------------------
SEGMENT_MERGE_DEG = 30.0      # consecutive moves within this many degrees form one segment
MIN_SEGMENT_M = 0.5           # segments shorter than this are dropped from the spoken route

# --- Output -----------------------------------------------------------------
OUTPUT_MODE = "both"          # "both", "light-only" or "voice-only" (stretch goal)

# --- Models and voices (no keys here: keys live in .env) ----------------------
# From the "Build with Gemini 4" hackathon builder guide (Nov 2026):
GEMINI_MODEL = "gemini-4-hydrogen"            # fast Gemini 4 for tool calls (free tier available)
GEMINI_DECISION_MODEL = "gemini-decision-1"   # Decisions API: pick tool / landmark with confidence
DECISION_MIN_CONFIDENCE = 0.75                # below this, ask the user instead of acting
ELEVENLABS_VOICE_ID = "SAz9YHcvj6GT2YYXdXww"   # River: calm, neutral, informative
MINIMAX_TTS_MODEL = "speech-2.8-turbo"         # backup voice when ElevenLabs fails (MiniMax T2A)
MINIMAX_VOICE_ID = "English_Insightful_Speaker"
LISTEN_SECONDS = 5.0          # fixed-window mode: how long one turn records
LISTEN_MODE = "toggle"        # "toggle": double-tap = mic on, double-tap again (or pause) = mic off
LISTEN_MAX_SECONDS = 15.0     # toggle mode: the mic always switches off after this
LISTEN_PAUSE_STOP_SECONDS = 2.0   # toggle mode: stop this long after the last word heard
VOICE_CHIMES = True           # short laptop sounds when the mic turns on (Tink) and off (Pop)

# --- Files ------------------------------------------------------------------
DATA_DIR = "data"
ROUTES_FILE = "data/routes.json"
LOG_DIR = "data/logs"
