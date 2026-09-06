import os
import sys
import json
import wave
import vosk

# Add project root to sys.path to import config if run directly
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.append(project_root)

import config

class VoskTranscriber:
    def __init__(self, model_path=None, sample_rate=16000):
        """
        Initialize the Vosk Transcriber.
        
        :param model_path: Path to the Vosk model directory. Defaults to config if None.
        :param sample_rate: Sample rate for the recognizer (must match audio source).
        """
        if model_path is None:
            model_path = os.getenv("VOSK_MODEL_PATH", config.VOSK_MODEL_PATH)
            
        if not os.path.exists(model_path):
            print(f"Error: Vosk model path '{model_path}' not found.")
            print("Please identify the correct path in config.py or download a model.")
            self.model = None
        else:
            try:
                # Vosk logs to stderr, which can be noisy.
                vosk.SetLogLevel(-1) 
                self.model = vosk.Model(model_path)
                print(f"Vosk model loaded from: {model_path}")
            except Exception as e:
                print(f"Failed to load Vosk model: {e}")
                self.model = None
                
        self.sample_rate = sample_rate

    def transcribe_wav_bytes(self, audio_bytes: bytes) -> str:
        """
        Transcribes raw PCM audio bytes to text.
        
        :param audio_bytes: Raw 16-bit PCM mono audio data.
        :return: Transcribed text string.
        """
        if not self.model or getattr(self, "model", None) is None:
            print("Transcriber or model not initialized.")
            return ""
            
        rec = vosk.KaldiRecognizer(self.model, self.sample_rate)
        rec.AcceptWaveform(audio_bytes)
        
        result_json = rec.FinalResult()
        result_dict = json.loads(result_json)
        return result_dict.get("text", "")

if __name__ == "__main__":
    def test_transcriber():
        print("Testing VoskTranscriber...")
        transcriber = VoskTranscriber()
        
        test_file = os.path.join(project_root, "test_recording.wav")
        if not os.path.exists(test_file):
            print(f"Test file '{test_file}' not found. Run recorder.py test first.")
            return

        print(f"Reading {test_file}...")
        try:
            with wave.open(test_file, "rb") as wf:
                if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
                    print("Warning: Audio format may not match Vosk requirements (16kHz, Mono, 16-bit).")
                
                audio_data = wf.readframes(wf.getnframes())
                
            print(f"Transcribing {len(audio_data)} bytes...")
            text = transcriber.transcribe_wav_bytes(audio_data)
            print("-" * 40)
            print(f"Transcript: '{text}'")
            print("-" * 40)
            
        except Exception as e:
            print(f"Error reading/transcribing file: {e}")

    test_transcriber()
