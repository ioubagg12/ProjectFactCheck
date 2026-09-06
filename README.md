# Voice Fact Checker

A local desktop application that continuously listens to your microphone and allows you to instantly fact-check the last 10 seconds of spoken audio against trusted sources using Google's Fact Check Tools API.

## Features

- **Background Audio Buffer**: Continuously records the last 10 seconds of audio into a ring buffer (memory efficient).
- **Offline Speech-to-Text**: Uses [Vosk](https://alphacephei.com/vosk/) for fast, private, offline transcription.
- **Instant Verification**: Queries the Google Fact Check Tools API with the transcribed text.
- **Global Hotkey**: Trigger a fact-check from anywhere in your OS (default: `F8`).
- **Terminal UI**: Clean textual output showing claims, ratings, and source URLs.

## Prerequisites

- Python 3.8 or higher.
- A working microphone.
- [Google Cloud API Key](https://console.cloud.google.com/) with "Fact Check Tools API" enabled.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/voice-fact-checker.git
    cd voice-fact-checker
    ```

2.  **Set up Python Environment**:
    ```bash
    python -m venv venv
    # Windows:
    .\venv\Scripts\activate
    # Mac/Linux:
    source venv/bin/activate
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    # Or manually:
    pip install pyaudio vosk requests keyboard python-dotenv
    ```
    *Note: If `pyaudio` fails to install on Windows, try `pip install pipwin && pipwin install pyaudio`.*

4.  **Download Speech Model**:
    - Download `vosk-model-small-en-us-0.15` from [Vosk Models](https://alphacephei.com/vosk/models).
    - Extract the folder into the project root.
    - Rename the folder to `model`.

5.  **Configure API Key**:
    - Create a `.env` file in the root directory.
    - Add your Google API Key:
      ```
      FACTCHECK_API_KEY=AIzaSyYourKeyHere...
      ```

## How to Use

1.  **Start the application** (Run as Admin if hotkeys don't register):
    ```bash
    python main.py
    ```

2.  **Speak naturally**. The app is listening to the last 10 seconds of audio buffer.
    > "I heard that the earth is actually flat."

3.  **Press the Hotkey** (Default: `F8`).

4.  **Read the results**: The app will transcribe your speech and print fact-check results:

    ```text
    CLAIM: i heard that the earth is actually flat

    1. [FALSE] - Snopes
       Claim reviewed: The earth is flat.
       Article: No, the earth is not flat.
       URL: https://snopes.com/...
    ```

5.  **Exit**: Press `Ctrl+C` in the terminal.

## Configuration

You can adjust settings in `config.py` or via environment variables:

| Setting | Description | Default |
| :--- | :--- | :--- |
| `HOTKEY` | Keyboard shortcut to trigger check | `f8` |
| `AUDIO_BUFFER_SECONDS` | How many seconds of audio to keep | `10` |
| `VOSK_MODEL_PATH` | Path to the downloaded model folder | `model` |

## Project Structure

```text
ProjectFactCeck/
├─ app.py                          # Flask route/controller layer
├─ config.py
├─ templates/
│  └─ index.html
├─ static/
│  ├─ css/style.css
│  └─ js/main.js
└─ src/
    ├─ services/
    │  └─ fact_check_pipeline.py    # Orchestration/business logic layer
    ├─ providers/
    │  ├─ stt/
    │  │  └─ vosk_transcriber.py    # Speech-to-text provider
    │  ├─ fact_check/
    │  │  └─ google_fact_checker.py # Google Fact Check provider
    │  └─ search/
    │     └─ serper_search.py       # Live web search provider (online mode)
    ├─ audio/
    └─ ui/
```
