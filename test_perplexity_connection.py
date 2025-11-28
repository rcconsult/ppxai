"""Quick test to check Perplexity API connection."""

import os
from dotenv import load_dotenv
from openai import OpenAI
import httpx

# Load environment variables
load_dotenv()

api_key = os.getenv("PERPLEXITY_API_KEY")
ssl_verify = os.getenv("SSL_VERIFY", "true").lower() != "false"

print(f"API Key loaded: {api_key[:10]}..." if api_key else "No API key found")
print(f"SSL Verification: {ssl_verify}")

# Try to connect
try:
    if not ssl_verify:
        http_client = httpx.Client(verify=False)
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai",
            http_client=http_client
        )
    else:
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )

    print("\nTesting simple chat completion...")
    response = client.chat.completions.create(
        model="sonar-pro",
        messages=[
            {"role": "user", "content": "Say 'Hello, I am working!' in one sentence."}
        ],
        stream=False
    )

    print(f"✓ Success! Response: {response.choices[0].message.content}")

except Exception as e:
    print(f"✗ Error: {type(e).__name__}: {str(e)}")
    import traceback
    traceback.print_exc()
