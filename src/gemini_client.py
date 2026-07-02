import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def call_gemini(prompt: str) -> str:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text

if __name__ == "__main__":
    print(call_gemini("Say hello and confirm you're working, in one sentence."))