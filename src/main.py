import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Create a request to the Chat Completions endpoint
response = client.chat.completions.create(
  model="gpt-4o-mini",
  messages=[
    {
      "role": "user", 
     "content": "Write a polite reply accepting an AI Engineer job offer."}]
)

print(response.choices[0].message.content)


