"""
LLM client wrapper for the Customer Service Agent.

Uses Azure OpenAI with managed identity (DefaultAzureCredential).
Optional fallback to Anthropic Claude API via environment flag.

Environment variables:
    AZURE_OPENAI_ENDPOINT         # e.g. https://payswitch-openai.openai.azure.com/
    AZURE_OPENAI_DEPLOYMENT       # e.g. gpt-4o-mini
    AZURE_OPENAI_API_VERSION      # e.g. 2024-10-21
    ANTHROPIC_API_KEY             # if set, use Claude instead of Azure OpenAI
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("payswitch-cs.customer_service.llm")

DEFAULT_MAX_TOKENS = 500
DEFAULT_TEMPERATURE = 0.2


class LLMError(Exception):
    """Raised when the LLM call fails."""


def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict[str, Any]:
    """
    Call the LLM with a system + user prompt and return the response.

    Args:
        system_prompt: System instructions for the model.
        user_prompt: User's message (includes question + context).
        max_tokens: Max tokens to generate.
        temperature: Sampling temperature.

    Returns:
        Dict with keys: answer (str), tokens_used (int), model (str), provider (str).

    Raises:
        LLMError: If the LLM call fails or no provider is configured.
    """
    # Prefer Anthropic if API key is set (explicit opt-in)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_anthropic(system_prompt, user_prompt, max_tokens, temperature)

    # Default: Azure OpenAI
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not endpoint or not deployment:
        raise LLMError(
            "No LLM provider configured. Set AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT, "
            "or ANTHROPIC_API_KEY."
        )

    return _call_azure_openai(
        system_prompt, user_prompt, max_tokens, temperature, endpoint, deployment,
    )


def _call_azure_openai(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    endpoint: str,
    deployment: str,
) -> dict[str, Any]:
    """
    Call Azure OpenAI.

    Uses API key auth if AZURE_OPENAI_API_KEY is set, otherwise
    falls back to managed identity via DefaultAzureCredential.
    """
    try:
        from openai import AzureOpenAI
    except ImportError as exc:
        raise LLMError(f"Missing dependency: {exc}")

    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")

    try:
        if api_key:
            client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
            )
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(),
                "https://cognitiveservices.azure.com/.default",
            )
            client = AzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider,
                api_version=api_version,
            )

        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        answer = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0

        return {
            "answer": answer,
            "tokens_used": tokens_used,
            "model": deployment,
            "provider": "azure_openai",
        }

    except Exception as exc:
        logger.exception("Azure OpenAI call failed")
        raise LLMError(f"Azure OpenAI call failed: {exc}") from exc


def _call_anthropic(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    """Call Anthropic Claude API (fallback / dev mode)."""
    try:
        import anthropic
    except ImportError as exc:
        raise LLMError(
            f"anthropic package not installed: {exc}. "
            "Install with 'pip install anthropic' or configure Azure OpenAI instead."
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        answer = "".join(block.text for block in response.content if hasattr(block, "text"))
        tokens_used = response.usage.input_tokens + response.usage.output_tokens

        return {
            "answer": answer,
            "tokens_used": tokens_used,
            "model": model,
            "provider": "anthropic",
        }

    except Exception as exc:
        logger.exception("Anthropic call failed")
        raise LLMError(f"Anthropic call failed: {exc}") from exc
