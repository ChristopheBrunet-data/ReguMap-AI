import os
import google.generativeai as genai
from dotenv import load_dotenv

def find_models():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    with open("models.txt", "w") as f:
        for m in genai.list_models():
            f.write(f"{m.name}\n")

if __name__ == "__main__":
    find_models()
