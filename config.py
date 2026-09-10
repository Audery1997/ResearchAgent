from ollama import Client


MODEL = "qwen3:8b"


client = Client(
    host="http://127.0.0.1:11434",
    trust_env=False,
    timeout=120.0,
)