import unittest
from unittest.mock import patch, MagicMock
import speech_recognition as sr

# Import the function to be tested
from speech_text import recognize_speech

class TestRecognizeSpeech(unittest.TestCase):

    @patch('speech_text.sr.Microphone')
    @patch('speech_text.sr.Recognizer')
    def test_successful_recognition(self, MockRecognizer, MockMicrophone):
        """Tests the function's behavior on a successful speech recognition."""
        # Configure the mock Recognizer instance
        mock_recognizer_instance = MockRecognizer.return_value
        mock_recognizer_instance.recognize_google.return_value = "hello world"

        # Call the function
        result = recognize_speech()

        # Assert that the result is what we expect
        self.assertEqual(result, "hello world")
        mock_recognizer_instance.adjust_for_ambient_noise.assert_called_once()
        mock_recognizer_instance.listen.assert_called_once()
        mock_recognizer_instance.recognize_google.assert_called_once()

    @patch('speech_text.sr.Microphone')
    @patch('speech_text.sr.Recognizer')
    def test_unknown_value_error(self, MockRecognizer, MockMicrophone):
        """Tests the function's handling of an UnknownValueError."""
        # Configure the mock to raise an error when recognize_google is called
        mock_recognizer_instance = MockRecognizer.return_value
        mock_recognizer_instance.recognize_google.side_effect = sr.UnknownValueError()

        result = recognize_speech()
        self.assertEqual(result, "Error: Google Web Speech API could not understand the audio.")

    @patch('speech_text.sr.Microphone')
    @patch('speech_text.sr.Recognizer')
    def test_request_error(self, MockRecognizer, MockMicrophone):
        """Tests the function's handling of a RequestError."""
        # Configure the mock to raise an error
        mock_recognizer_instance = MockRecognizer.return_value
        error_message = "API unavailable"
        mock_recognizer_instance.recognize_google.side_effect = sr.RequestError(error_message)

        result = recognize_speech()
        self.assertEqual(result, f"Error: Could not request results from Google Web Speech API; {error_message}")

if __name__ == '__main__':
    unittest.main()