# Voice Fact Checker - Implementation & Setup Guide

## 1. Environment Setup
- [ ] Install Python 3.8+
- [ ] Create a virtual environment: `python -m venv venv`
- [ ] Activate the virtual environment:
    - Windows: `venv\Scripts\activate`
    - Linux/Mac: `source venv/bin/activate`
- [ ] Install dependencies:
    ```bash
    pip install pyaudio vosk requests keyboard python-dotenv numpy
    ```
    *(Note: Windows users may need `pipwin install pyaudio` if standard installation fails)*

## 2. Vosk Model Setup (Speech-to-Text)
- [ ] Go to [Vosk Models](https://alphacephei.com/vosk/models).
- [ ] Download a lightweight model (e.g., `vosk-model-small-en-us-0.15`).
- [ ] Extract the zip file into the project root directory.
- [ ] Rename the extracted folder to `model` (or update `VOSK_MODEL_PATH` in `config.py`).

## 3. Google API Setup (Fact Checking)
- [x] Go to the [Google Cloud Console](https://console.cloud.google.com/).
- [x] Create a new project (e.g., "VoiceFactChecker").
- [x] Navigate to **APIs & Services > Library**.
- [x] Search for **"Fact Check Tools API"** and click **Enable**.
- [x] Go to **APIs & Services > Credentials**.
- [x] Click **Create Credentials > API Key**.
- [x] Copy the key string.
- [x] Create a file named `.env` in the project root.
- [x] Add your key: `FACTCHECK_API_KEY=AIzaSy...your_key_here`

## 4. Running the App
- [ ] Run the application with administrator privileges (required for global hotkeys):
    ```bash
    python main.py
    ```
- [ ] Wait for "Recording started..." message.
- [ ] Press **F8** (or your configured hotkey) after speaking a claim.
- [ ] View the transcription and fact-check results in the terminal.
