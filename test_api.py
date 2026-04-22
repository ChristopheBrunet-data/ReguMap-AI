import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

def test_connection():
    load_dotenv()
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY is missing from .env")
        return
        
    print("Found GEMINI_API_KEY. Initializing Langchain ChatGoogleGenerativeAI...")
    
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.0,
            google_api_key=api_key
        )
        
        print("Sending test prompt to gemini-2.5-flash...")
        response = llm.invoke("Say exactly this: 'Hello ReguMap'")
        
        if "Hello ReguMap" in response.content:
            print(f"Success! Received: {response.content.strip()}")
        else:
            print(f"Reached model, but received unexpected response: {response.content}")
            
    except Exception as e:
        print(f"Error communicating with Gemini API via Langchain: {e}")

if __name__ == "__main__":
    test_connection()
