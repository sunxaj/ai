import speech_recognition as sr
import pyttsx3
import google.generativeai as genai
import os

def recognize_speech():
    """
    Listens for speech via the default microphone and converts it to text.

    Returns:
        str: The recognized text, or an error message if recognition fails.
    """
    # Initialize the recognizer and set the language to Chinese
    recognizer = sr.Recognizer()

    # Use the default microphone as the audio source
    with sr.Microphone() as source:
        print("Adjusting for ambient noise, please wait...")
        # Adjust the recognizer sensitivity to ambient noise
        recognizer.adjust_for_ambient_noise(source, duration=1)
        
        print("Listening... Please say something.")
        
        try:
            # Listen for the first phrase and extract it into audio data
            audio_data = recognizer.listen(source, timeout=5)
            print("Recognizing...")
            
            # Recognize speech using Google Web Speech API
            text = recognizer.recognize_google(audio_data, language='zh-CN') # Set language to Chinese
            return text
        except sr.WaitTimeoutError:
            return "Error: No speech detected within the timeout period."
        except sr.UnknownValueError:
            return "Error: Google Web Speech API could not understand the audio."
        except sr.RequestError as e:
            return f"Error: Could not request results from Google Web Speech API; {e}"

def ask_gemini(question):
    """
    Sends a question to the Gemini AI and returns the answer.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Error: GEMINI_API_KEY environment variable not set."
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(question)
        # Clean up the response text
        answer = response.text.replace('*', '').replace('`', '')
        return answer
    except Exception as e:
        return f"Error communicating with Gemini AI: {e}"


def speak_text(text, rate=160, pitch=50):
    """
    Converts text to speech using the 'espeak' engine for a robotic voice.
    :param text: The text to be spoken.
    :param rate: The speaking rate in words per minute.
    :param pitch: The pitch of the voice (0-99).
    """
    try:
        # Initialize with the espeak driver for a more robotic voice
        engine = pyttsx3.init(driverName='espeak') 
        engine.setProperty('voice', 'zh') # Set espeak voice to Chinese

        # Set speaking rate
        engine.setProperty('rate', rate)
        
        # Espeak allows for direct pitch modification
        # This requires a bit of a workaround to set raw voice properties
        # For Chinese, we'll just set the base 'zh' voice and adjust pitch
        # engine.setProperty('voice', f'{voice}+f3') # This might not work well with 'zh'
        engine.setProperty('pitch', pitch)
        
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"Error initializing or using text-to-speech engine: {e}")

if __name__ == "__main__":
    # 1. Listen for a question
    question = recognize_speech()
    print("\nYour Question:")
    print(f"-> {question}")

    # 2. If the question is valid, send it to Gemini
    if not question.startswith("Error:"):
        print("\nAsking Gemini...")
        answer = ask_gemini(question)
        
        # 3. Print and speak the answer
        print("\nGemini's Answer:")
        print(f"-> {answer}")
        
        if not answer.startswith("Error:"):
            print("\nSpeaking the answer...")
            # Use a slightly more natural rate for the answer
            speak_text(answer, rate=150, pitch=50)
    else:
        # If there was an error in speech recognition, speak the error
        speak_text(question)