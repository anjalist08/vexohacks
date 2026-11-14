"""Every tunable value in one place. Only one person edits this file (see AGENTS.md).

Values marked PLACEHOLDER are guesses until the Gate B walk test measures them.
Do not quote accuracy numbers from them.
"""

# --- Band -------------------------------------------------------------------
# The number on your band's bag (the band is called Vexo-HACK-NN).
# Nothing connects to a band, real or pretend, until this is set.
# Never use 42 or any other number from the kit's examples.
BAND = 80

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
GEMINI_MODEL = None           # confirm the Gemini 4 model id in the sponsor channel
ELEVENLABS_VOICE_ID = "SAz9YHcvj6GT2YYXdXww"   # River: calm, neutral, informative
LISTEN_SECONDS = 4.0          # how long one tap-to-talk turn records

# --- Files ------------------------------------------------------------------
DATA_DIR = "data"
ROUTES_FILE = "data/routes.json"
LOG_DIR = "data/logs"
