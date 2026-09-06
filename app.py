import os
import wave
import uuid
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from groq import Groq

import config
from src.providers.stt import VoskTranscriber
from src.providers.fact_check import FactChecker
from src.providers.search import SerperSearcher
from src.services import FactCheckPipeline

# Load Environment
load_dotenv()

app = Flask(__name__)
APP_MODE = os.getenv("APP_MODE", "offline").strip().lower()
if APP_MODE not in {"offline", "online"}:
    APP_MODE = "offline"

# Initialize singletons
print("Initializing AI Models...")
transcriber = VoskTranscriber(model_path=config.VOSK_MODEL_PATH)
fact_checker = FactChecker()
serper_searcher = SerperSearcher()

# Initialize Groq client
groq_client = None
if os.getenv("GROQ_API_KEY"):
    try:
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        print("Groq Client Initialized.")
    except Exception as e:
        print(f"Failed to initialize Groq: {e}")
else:
    print("GROQ_API_KEY not found. Using basic keyword cleaner.")

print(f"Running mode: {APP_MODE}")

pipeline = FactCheckPipeline(
    transcriber=transcriber,
    fact_checker=fact_checker,
    serper_searcher=serper_searcher,
    groq_client=groq_client,
    default_mode=APP_MODE,
)

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/modes', methods=['GET'])
def get_modes():
    return jsonify({
        "available_modes": ["offline", "online"],
        "available_input_methods": ["mic", "text"],
        "default_mode": APP_MODE,
    })

@app.route('/api/check', methods=['POST'])
def check_audio():
    if 'audio_data' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    
    audio_file = request.files['audio_data']
    requested_mode = request.form.get("mode", APP_MODE)
    
    # Generate temp filename
    filename = f"temp_{uuid.uuid4()}"
    input_path = f"{filename}.wav"
    
    try:
        # The browser JS now sends a proper 16kHz WAV file.
        # We can directly read it or pass it to transformers.
        audio_file.save(input_path)
        
        # Read the WAV file
        with wave.open(input_path, "rb") as wf:
             # Verify format just in case
             if wf.getnchannels() != 1 or wf.getframerate() != 16000:
                 print(f"Warning: Audio format {wf.getnchannels()}ch {wf.getframerate()}Hz might be incompatible.")
             
             audio_data = wf.readframes(wf.getnframes())
        
        response_payload = pipeline.process_claim_from_audio(
            input_path=input_path,
            audio_data=audio_data,
            requested_mode=requested_mode,
        )
        
        return jsonify(response_payload)

    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        # Cleanup
        if os.path.exists(input_path):
            try:
                os.remove(input_path)
            except:
                pass


@app.route('/api/check-text', methods=['POST'])
def check_text():
    payload = request.get_json(silent=True) or {}
    claim_text = (payload.get('claim_text') or "").strip()
    requested_mode = payload.get("mode", APP_MODE)

    if not claim_text:
        return jsonify({"error": "No claim text provided"}), 400

    try:
        response_payload = pipeline.process_claim_from_text(
            claim_text=claim_text,
            requested_mode=requested_mode,
        )
        return jsonify(response_payload)
    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Starting Flask Server...")
    print("Please open http://127.0.0.1:5000 in your browser")
    app.run(debug=True, port=5000)
