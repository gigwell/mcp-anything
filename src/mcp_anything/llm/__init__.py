"""LLM provider abstraction for mcp-anything.

Supports two protocols:
- anthropic: Anthropic Claude (Messages API)
- openai: OpenAI-compatible (Completions API)

Configured via environment variables:
- MCP_ANYTHING_API_TYPE: 'anthropic' or 'openai' (default: 'anthropic')
- MCP_ANYTHING_MODEL: Model name (default: 'claude-sonnet-4-20250514')
- MCP_ANYTHING_API_URL: Base URL for OpenAI-compatible (default: OpenAI API)
- MCP_ANYTHING_API_KEY: API key
"""

import os


def complete(prompt: str, max_tokens: int = 4096) -> str:
    """Send prompt to configured LLM, return response text.

    Args:
        prompt: The prompt to send to the LLM
        max_tokens: Maximum tokens in response

    Returns:
        The LLM's response text

    Raises:
        ValueError: If MCP_ANYTHING_API_TYPE is unknown
    """
    api_type = os.environ.get("MCP_ANYTHING_API_TYPE", "anthropic")

    if api_type == "anthropic":
        from mcp_anything.llm.anthropic import complete as _complete
    elif api_type == "openai":
        from mcp_anything.llm.openai import complete as _complete
    else:
        raise ValueError(f"Unknown MCP_ANYTHING_API_TYPE: {api_type}")

    return _complete(prompt, max_tokens)
