from openai import OpenAI
from config import OPENAI_API_KEY

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not set")

client = OpenAI(api_key=OPENAI_API_KEY)


def premium_reasoning(question: str):
    """
    Uses OpenAI Responses API for high-quality, structured reasoning.
    Returns the generated text answer.
    """
    response = client.responses.create(
        model="gpt-4.1-mini",  # Cheap/fast; upgrade to o4-mini / gpt-5-mini / o1 variants for deeper reasoning if budget allows
        # For simple single-turn: can use a plain string
        input=f"""
You are a strategic intelligence AI.

Give a high-level, structured, clear and deep answer to:

{question}
""",
        # Optional: force plain text output, control verbosity
        text={
            "format": {"type": "text"},  # or "json_schema" later if you want structured JSON
            "verbosity": "detailed"      # or "concise" / default
        },
        # Optional: if using a reasoning-capable model
        # reasoning={"effort": "medium"},  # low/medium/high — only on supported models
        # max_tokens=2048,
    )

    # Access the output (Responses API typically provides .output_text or similar)
    # Exact attribute: check response.model_dump() if needed, but common patterns:
    return response.output_text  # Preferred in many 2026 examples
    # Fallback/alternative: response.choices[0].message.content if it mirrors chat shape
