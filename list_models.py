import os
import google.generativeai as genai
from dotenv import load_dotenv

def list_models():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("No API key.")
        return
        
    genai.configure(api_key=api_key)
    print("Listing available models for this key...")
    try:
        for m in genai.list_models():
            print(f"Name: {m.name}, Supported methods: {m.supported_generation_methods}")
    except Exception as e:
        print(f"Failed to list models: {e}")

if __name__ == "__main__":
    list_models()
