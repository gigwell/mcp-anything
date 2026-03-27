"""Anthropic Claude provider using Messages API."""

import os

import anthropic


def complete(prompt: str, max_tokens: int) -> str:
    """Send prompt to Anthropic Claude, return response text.

    Args:
        prompt: The prompt to send
        max_tokens: Maximum tokens in response

    Returns:
        The response text
    """
    api_key = os.environ.get("MCP_ANYTHING_API_KEY")
    model = os.environ.get("MCP_ANYTHING_MODEL", "claude-sonnet-4-20250514")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text
