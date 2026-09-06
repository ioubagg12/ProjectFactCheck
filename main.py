import sys
import os
import signal
import time
import keyboard
from dotenv import load_dotenv

import config
from src.audio.recorder import AudioBufferRecorder
from src.providers.stt import VoskTranscriber
from src.providers.fact_check import FactChecker
from src.ui.interface import FactCheckApp

def main():
    # 1. Load Environment Variables
    load_dotenv()
    print("Environment variables loaded.")

    print("\n=== Voice Fact Checker Starting ===")
    
    # Check for critical configuration
    if not os.environ.get("FACTCHECK_API_KEY") and config.GOOGLE_API_KEY == "YOUR_API_KEY_HERE":
        print("WARNING: No Fact Check API Key configured. Results will fail.")
        print("Set FACTCHECK_API_KEY in .env or config.py.")

    # 2. Initialize Components via the App wrapper
    # We use the FactCheckApp class from interface.py which already orchestrates these,
    # but we can optionally instantiate them here if we wanted dependency injection.
    # For simplicity, we'll let FactCheckApp handle the wiring as designed in that module.
    
    hotkey = os.environ.get("HOTKEY", config.HOTKEY)
    buffer_duration = config.AUDIO_BUFFER_SECONDS
    
    try:
        app = FactCheckApp(hotkey=hotkey, buffer_seconds=buffer_duration)
    except Exception as e:
        print(f"Failed to initialize application: {e}")
        return

    # 3. Start Recording & Listening
    try:
        print("\n[System] Starting audio recorder...")
        app.recorder.start()
        
        # Setup Hotkey
        # We use the method directly from the app instance
        keyboard.add_hotkey(hotkey, app.handle_hotkey)
        
        print(f"[System] Listening for Global Hotkey: {hotkey.upper()}")
        print(f"[System] Buffer Duration: {buffer_duration} seconds")
        print("[System] Press Ctrl+C to exit program.")
        
        # 4. Main Loop / Wait
        # specific infinite wait that handles interrupts better than keyboard.wait() sometimes
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n[System] Shutdown requested by user.")
    except Exception as e:
        print(f"\n[Error] Unexpected exception: {e}")
    finally:
        # 5. Graceful Shutdown
        print("[System] Stopping audio recorder...")
        app.shutdown()
        print("[System] Exiting cleanly.")

if __name__ == "__main__":
    main()
