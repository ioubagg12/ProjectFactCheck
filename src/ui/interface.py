import sys
import os
import time
import threading
import keyboard
import wave
import struct
import numpy as np

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.append(project_root)

# Import our modules
try:
    from src.audio.recorder import AudioBufferRecorder
    from src.providers.stt import VoskTranscriber
    from src.providers.fact_check import FactChecker
except ImportError as e:
    print(f"Import Error: {e}")
    print("Ensure src.audio and src.providers modules are implemented.")

class FactCheckApp:
    def __init__(self, hotkey="f8", buffer_seconds=10):
        self.hotkey = hotkey
        self.buffer_seconds = buffer_seconds
        
        print("Initializing components...")
        self.recorder = AudioBufferRecorder(buffer_duration=buffer_seconds)
        self.transcriber = VoskTranscriber()
        self.fact_checker = FactChecker()
        self.is_processing = False

    def handle_hotkey(self):
        """Callback triggered when hotkey is pressed."""
        if self.is_processing:
            print("Already processing request...")
            return

        self.is_processing = True
        print(f"\n[Hotkey {self.hotkey.upper()} Pressed!] Capturing audio...")
        
        # Run processing in a separate thread so we don't block the keyboard hook
        threading.Thread(target=self._process_workflow, daemon=True).start()

    def _process_workflow(self):
        try:
            # 1. Get Audio
            audio_data = self.recorder.get_last_seconds(self.buffer_seconds)
            if not audio_data:
                print("No audio data captured.")
                self.is_processing = False
                return

            print(f"Captured {len(audio_data)} bytes. Transcribing...")

            # 2. Transcribe
            transcript = self.transcriber.transcribe_wav_bytes(audio_data)
            print(f"\n--> Transcript: \"{transcript}\"")
            
            if not transcript or not transcript.strip():
                print("No speech detected.")
                self.is_processing = False
                return

            # 3. Fact Check
            print("Searching fact checks...")
            results = self.fact_checker.search_claims(transcript)
            
            # 4. Display Results
            self.display_results(transcript, results)

        except Exception as e:
            print(f"Error during processing flow: {e}")
        finally:
            self.is_processing = False
            print("\nReady.")

    def display_results(self, transcript, results):
        print("\n" + "="*50)
        print(f"CLAIM: {transcript}")
        print("="*50)
        
        if not results:
            print("No matching fact checks found.")
        else:
            for i, res in enumerate(results, 1):
                rating_str = f"[{res.rating.upper()}]"
                print(f"\n{i}. {rating_str} - {res.publisher}")
                print(f"   Claim reviewed: {res.claim}")
                print(f"   Article: {res.text}")
                print(f"   URL: {res.url}")
        print("="*50)

    def shutdown(self):
        if hasattr(self, 'recorder'):
            self.recorder.stop()
            self.recorder.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Voice Fact Checker UI")
    parser.add_argument("--hotkey", default="f8", help="Global hotkey to trigger fact check (e.g., f8, ctrl+shift+z)")
    args = parser.parse_args()
    
    print(f"Starting Voice Fact Checker...")
    app = FactCheckApp(hotkey=args.hotkey)
    
    try:
        # Start recording immediately
        app.recorder.start()
        
        # Setup hotkey listener
        keyboard.add_hotkey(args.hotkey, app.handle_hotkey)
        
        print(f"Listening... Press [{args.hotkey.upper()}] to fact check the last {app.buffer_seconds} seconds.")
        print("Press Ctrl+C to exit.")
        
        # Keep main thread alive
        keyboard.wait()
        
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'app' in locals():
            app.shutdown()
