"""OpenAI-compatible provider using Completions API.

Works with OpenAI, LMStudio, Ollama, and any OpenAI-compatible server.
"""

import os

import httpx


def complete(prompt: str, max_tokens: int) -> str:
    """Send prompt to OpenAI-compatible API, return response text.

    Args:
        prompt: The prompt to send
        max_tokens: Maximum tokens in response

    Returns:
        The response text

    Raises:
        httpx.HTTPStatusError: If the API request fails
    """
    base_url = os.environ.get("MCP_ANYTHING_API_URL", "https://api.openai.com/v1")
    api_key = os.environ.get("MCP_ANYTHING_API_KEY", "")
    model = os.environ.get("MCP_ANYTHING_MODEL", "gpt-4o")

    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]
