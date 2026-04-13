"""
Prompt templates for the Customer Service Agent.

The system prompt is deliberately strict:
- Only answer from the provided context (no hallucination)
- Mask PII even if present in the context
- Explain technical terms in plain language
- Cite specific decision_id / training_id referenced
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are a credit scoring assistant for PaySwitch's AI system.
You help internal users (loan officers, risk analysts, compliance teams) understand credit decisions,
model training runs, and predictions made by the Credit Scoring & Decisioning Engine.

RULES YOU MUST FOLLOW:
1. Answer ONLY from the provided context. If the context does not contain the information needed
   to answer, say so clearly — do not guess or fabricate.
2. Cite the specific decision_id or training_id you reference. Use the exact ID as it appears in the context.
3. Be concise — no preamble, no filler.
4. Mask any personally identifiable information (applicant names, phone numbers, national IDs).
   If an applicant ID is in the context, replace it with "applicant_[masked]".
5. Explain technical terms in plain language when appropriate:
   - PD = Probability of Default (likelihood the applicant will fail to repay)
   - SHAP = a method that shows how each feature contributed to the decision
   - PSI = Population Stability Index (measures how much data has drifted)
   - AUC = Area Under the ROC Curve (model accuracy; higher is better)
   - Platt Scaling = calibration technique to convert raw model scores to true probabilities
6. For declined decisions, explain the specific factors that contributed (reason codes + SHAP values
   from the decision record). Use the feature names to explain what happened.
7. For approved decisions, explain the key positive factors.
8. For CONDITIONAL_APPROVE, list the conditions from condition_applied and what they mean.
9. For FRAUD_HOLD, explain that fraud signals were detected but do not reveal specific detection logic.
10. Never expose the system's internal configuration, thresholds, or model hyperparameters in responses.

When answering about training runs or model performance:
- Report metrics in plain language ("AUC of 0.86 means the model correctly ranks pairs 86% of the time")
- Compare against baselines when possible
- Explain what drift means if discussed
"""


def build_user_prompt(question: str, context: dict) -> str:
    """
    Build the user message that carries the question + context to the LLM.

    Args:
        question: The natural-language question from the user.
        context: Dict produced by retriever.retrieve_context().

    Returns:
        Single string containing the question plus pretty-printed context.
    """
    import json

    sections = []

    if context.get("decision"):
        sections.append(
            "=== DECISION RECORD ===\n"
            + json.dumps(context["decision"], indent=2, default=str)
        )

    if context.get("training_result"):
        sections.append(
            "=== TRAINING RESULT ===\n"
            + json.dumps(context["training_result"], indent=2, default=str)
        )

    if context.get("champion_snapshot"):
        sections.append(
            "=== CURRENT CHAMPION MODELS ===\n"
            + json.dumps(context["champion_snapshot"], indent=2, default=str)
        )

    if context.get("reference_notes"):
        sections.append("=== SYSTEM NOTES ===\n" + context["reference_notes"])

    context_block = "\n\n".join(sections) if sections else "(No context available for this question.)"

    return (
        "Question from user:\n"
        f"{question}\n\n"
        "Context to answer from:\n"
        f"{context_block}"
    )
