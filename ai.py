from openai import OpenAI
from config import OPENAI_API_KEY

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not set")

client = OpenAI(api_key=OPENAI_API_KEY)


def premium_reasoning(question: str):
    """
    High-quality paid reasoning endpoint.
    Focused on structured thinking, decision clarity, and strategic insight.
    """

    prompt = f"""
You are a high-level strategic intelligence system.

Your goal is NOT to give a generic answer.
Your goal is to deliver clear thinking that helps a human or an AI agent make a better decision.

Answer the following question with:

1) Core insight (what actually matters here)
2) Deep reasoning (not surface-level explanation)
3) Clear structure
4) Practical conclusion (what should be done / what this means)

Question:
{question}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        text={
            "format": {"type": "text"},
            "verbosity": "detailed"
        },
    )

    return response.output_text
