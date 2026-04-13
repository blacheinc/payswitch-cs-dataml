"""
HTTP handler for the Customer Service Agent.

Orchestrates context retrieval → LLM call → response construction.
Kept separate from function_app.py so it can be unit-tested without
the Functions runtime.
"""

from __future__ import annotations

import logging
from typing import Any

from .llm_client import LLMError, call_llm
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .retriever import retrieve_context

logger = logging.getLogger("payswitch-cs.customer_service.handlers")

MAX_TOKENS_DEFAULT = 500
MAX_TOKENS_LIMIT = 2000


def handle_explain_request(
    blob_service_client,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Process a customer service NL question.

    Args:
        blob_service_client: BlobServiceClient instance.
        payload: {
            "question": str,                  # required
            "decision_id": str,               # optional
            "training_id": str,               # optional
            "max_tokens": int,                # optional, capped at MAX_TOKENS_LIMIT
        }

    Returns:
        Dict: {answer, context_used, model, tokens_used, provider}

    Raises:
        ValueError: on missing/invalid required inputs.
        LLMError: on LLM call failure.
    """
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")

    question = payload.get("question")
    if not question or not isinstance(question, str):
        raise ValueError("'question' is required and must be a string")
    if len(question) > 2000:
        raise ValueError("'question' must be at most 2000 characters")

    decision_id = payload.get("decision_id")
    training_id = payload.get("training_id")

    max_tokens = payload.get("max_tokens", MAX_TOKENS_DEFAULT)
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        raise ValueError("'max_tokens' must be an integer")
    max_tokens = max(50, min(max_tokens, MAX_TOKENS_LIMIT))

    # Retrieve context
    context = retrieve_context(
        blob_service_client,
        question=question,
        decision_id=decision_id,
        training_id=training_id,
    )

    # Build user prompt + call LLM
    user_prompt = build_user_prompt(question, context)
    logger.info(
        "Explain request: question_len=%d decision_id=%s training_id=%s",
        len(question), decision_id or "-", training_id or "-",
    )

    llm_response = call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
    )

    # Describe what context we actually used
    context_used = []
    if context.get("decision"):
        context_used.append(f"decision:{decision_id}")
    if context.get("training_result"):
        context_used.append(f"training:{training_id}")
    if context.get("champion_snapshot"):
        context_used.append("champion_snapshot")
    if context.get("reference_notes"):
        context_used.append("reference_notes")

    return {
        "answer": llm_response["answer"],
        "context_used": context_used,
        "model": llm_response["model"],
        "provider": llm_response["provider"],
        "tokens_used": llm_response["tokens_used"],
    }
