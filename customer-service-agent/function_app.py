"""
PaySwitch Customer Service Agent — Azure Function App.

Single HTTP endpoint (POST /v1/explain) that answers natural-language
questions about credit decisions, training runs, and model performance.

Uses Azure OpenAI (via managed identity) with blob-stored audit records
and champion metadata as context.

BLD Section 5.1 — Customer Service Agent with LLM-assisted explanations.
"""

from __future__ import annotations

import json
import logging
import os

import azure.functions as func

logger = logging.getLogger("payswitch-cs.customer-service")

app = func.FunctionApp()

STORAGE_CONNECTION = os.environ.get("STORAGE_CONNECTION", "")


@app.function_name("api_explain")
@app.route(route="v1/explain", auth_level=func.AuthLevel.FUNCTION, methods=["POST"])
def api_explain(req: func.HttpRequest) -> func.HttpResponse:
    """
    Natural language explanation endpoint.

    Request body:
        {
          "question": "Why was REQ-abc declined?",
          "decision_id": "REQ-abc",          # optional
          "training_id": "TRAIN-...",        # optional
          "max_tokens": 500                  # optional, capped at 2000
        }

    Response (200):
        {
          "answer": "...",
          "context_used": ["decision:REQ-abc", "champion_snapshot"],
          "model": "gpt-4o-mini",
          "provider": "azure_openai",
          "tokens_used": 423
        }
    """
    from azure.storage.blob import BlobServiceClient

    from modules.handlers import handle_explain_request
    from modules.llm_client import LLMError

    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "bad_request", "detail": "Body must be valid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        result = handle_explain_request(blob_client, payload)
        logger.info(
            "Explain answered: tokens=%d context=%s",
            result.get("tokens_used", 0),
            result.get("context_used"),
        )
        return func.HttpResponse(
            json.dumps(result, default=str),
            status_code=200,
            mimetype="application/json",
        )
    except ValueError as ve:
        return func.HttpResponse(
            json.dumps({"error": "validation_error", "detail": str(ve)}),
            status_code=422,
            mimetype="application/json",
        )
    except LLMError as le:
        logger.exception("LLM error")
        return func.HttpResponse(
            json.dumps({"error": "llm_error", "detail": str(le)}),
            status_code=502,
            mimetype="application/json",
        )
    except Exception:
        logger.exception("api_explain failed")
        return func.HttpResponse(
            json.dumps({"error": "internal_error"}),
            status_code=500,
            mimetype="application/json",
        )
