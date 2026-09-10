from ollama import Client


client = Client(
    host="http://127.0.0.1:11434",
    trust_env=False,
    timeout=120.0,
)


response = client.chat(
    model="qwen3:8b",
    messages=[
        {
            "role": "user",
            "content": "只回答一句：Local ResearchAgent is ready."
        }
    ],
    think=False,
)


print(response.message.content)