import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing. Check the .env file.")

client = genai.Client(api_key=api_key)
model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

response = client.models.generate_content(
    model=model_name,
    contents="Hello from DeepFind"
)

print(response.text)