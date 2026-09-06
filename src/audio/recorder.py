import pyaudio
import threading
import wave
import time
import collections
import os

class AudioBufferRecorder:
    def __init__(self, rate=16000, channels=1, chunk=4096, buffer_duration=10):
        """
        Initialize the AudioBufferRecorder.
        
        :param rate: Sample rate (default 16000 for Vosk).
        :param channels: Number of channels (default 1 for Mono).
        :param chunk: Frames per buffer processing chunk.
        :param buffer_duration: Total seconds of audio to keep in the ring buffer.
        """
        self.rate = rate
        self.channels = channels
        self.chunk = chunk
        self.format = pyaudio.paInt16
        self.buffer_duration = buffer_duration
        
        # Calculate maxlen to hold approx 'buffer_duration' seconds
        # chunks_per_second = rate / chunk
        self.maxlen = int((self.rate / self.chunk) * self.buffer_duration)
        
        # Deque of bytes objects (thread-safe for append/pop operations)
        self.frames = collections.deque(maxlen=self.maxlen)
        
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.is_recording = False
        self.record_thread = None
        self._stop_event = threading.Event()

    def start(self):
        """Starts the background recording thread."""
        if self.is_recording:
            return

        self.stream = self.p.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk
        )
        
        self.is_recording = True
        self._stop_event.clear()
        self.record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self.record_thread.start()
        print("Recording started...")

    def _record_loop(self):
        """Background loop to read from microphone and update buffer."""
        while self.is_recording and not self._stop_event.is_set():
            try:
                # Read raw bytes from stream
                data = self.stream.read(self.chunk, exception_on_overflow=False)
                self.frames.append(data)
            except Exception as e:
                print(f"Error recording: {e}")
                break

    def stop(self):
        """Stops the recording thread and closes the stream."""
        self.is_recording = False
        self._stop_event.set()
        
        if self.record_thread:
            self.record_thread.join()
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

    def close(self):
        """Terminates the PyAudio instance."""
        self.p.terminate()

    def get_last_seconds(self, seconds: int) -> bytes:
        """
        Returns the raw PCM audio bytes for the last 'seconds' duration.
        """
        if not self.frames:
            return b""

        # Calculate how many chunks cover the requested seconds
        chunks_needed = int((self.rate / self.chunk) * seconds)
        
        # Get the corresponding slice from the deque
        current_frames = list(self.frames)
        
        if len(current_frames) > chunks_needed:
            relevant_frames = current_frames[-chunks_needed:]
        else:
            relevant_frames = current_frames
            
        return b"".join(relevant_frames)
    
    def save_wav(self, file_path, audio_data):
        """Helper to save raw bytes to a proper WAV file."""
        with wave.open(file_path, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.p.get_sample_size(self.format))
            wf.setframerate(self.rate)
            wf.writeframes(audio_data)

if __name__ == "__main__":
    print("Testing AudioBufferRecorder...")
    recorder = AudioBufferRecorder()
    
    try:
        recorder.start()
        
        print("Recording for 5 seconds...")
        time.sleep(5)
        
        print("Capturing last 5 seconds of audio...")
        data = recorder.get_last_seconds(5)
        
        filename = "test_recording.wav"
        recorder.save_wav(filename, data)
        
        print(f"Saved {len(data)} bytes to {os.path.abspath(filename)}")
        
    finally:
        recorder.stop()
        recorder.close()

