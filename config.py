import os

# Voice Fact Checker Configuration

# --- Audio Settings ---
SAMPLE_RATE = 16000          # Hertz (Vosk requires 16k)
AUDIO_BUFFER_SECONDS = 10    # Duration of audio to keep in memory
CHANNELS = 1                 # Mono audio
CHUNK_SIZE = 4096            # Frames per buffer chunk

# --- Speech-to-Text (STT) ---
# Path to the unzipped Vosk model folder. 
# You can set this via env var VOSK_MODEL_PATH or keep strictly local.
# We check if the user extracted it with a subdirectory
_base_model_path = "model"
_sub_folder = "vosk-model-small-en-us-0.15"
if os.path.exists(os.path.join(_base_model_path, _sub_folder)):
    VOSK_MODEL_PATH = os.path.join(_base_model_path, _sub_folder)
else:
    VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", _base_model_path)

# --- Fact Check API ---
# Google Fact Check Tools API Key.
# HIGHLY RECOMMENDED: Set 'FACTCHECK_API_KEY' in your .env file or environment variables.
GOOGLE_API_KEY = os.getenv("FACTCHECK_API_KEY", "YOUR_API_KEY_HERE")
MAX_SEARCH_RESULTS = 3       # Number of fact-check results to display

# --- User Interface ---
# Hotkey to trigger the capture and check.
# Examples: "f8", "ctrl+shift+f", "alt+c"
HOTKEY = os.getenv("HOTKEY", "f8")
