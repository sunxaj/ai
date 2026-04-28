# AI Voice Assistant & System Dashboard

This project contains two main components:
1.  An **AI Voice Assistant** that listens for questions, gets answers from Google's Gemini AI, and speaks the results.
2.  A **System Stats Server & Slideshow** that displays system metrics and a photo slideshow in a browser.

---

## AI Voice Assistant (`speech_text.py`)

This component acts as a voice-controlled assistant. It listens for a question in Chinese, sends it to Google's Gemini AI for an answer, and then speaks the answer back using a synthesized voice.

### Setup & Installation

1.  **System Dependencies:**
    This script requires `PortAudio` for microphone access and `espeak-ng` for the voice engine.

    *   **On macOS:**
        ```bash
        brew install portaudio espeak-ng
        ```
    *   **On Debian/Ubuntu:**
        ```bash
        sudo apt-get install portaudio19-dev espeak-ng
        ```

2.  **Python Packages:**
    Install the required Python libraries into your virtual environment (`./venv`).
    ```bash
    pip install speechrecognition pyaudio pyttsx3 google-generativeai
    ```

3.  **Gemini API Key:**
    You need a Gemini API key from Google AI Studio. Set it as an environment variable:
    ```bash
    export GEMINI_API_KEY="YOUR_API_KEY"
    ```

### Run the Assistant

Activate your virtual environment and run the script:
```bash
source ./venv/bin/activate
python speech_text.py
```

---

## System Stats Server + Slideshow

This component contains a fullscreen slideshow (`slide.html`) and a tiny local server that exposes system stats at `/stats`.

### Server Setup (Python + Flask + psutil)

1. Install dependencies:

```bash
pip install Flask psutil
```

2. Run the server from the project root:

```bash
python3 sys_stats_server.py
```

3. Open in your browser:

http://localhost:5000/slide.html

The page will try to fetch `/stats` to show precise CPU/memory usage. If the server isn't running, the page falls back to approximate browser-provided data.
