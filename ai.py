from openai import OpenAI
import json
from config import OPENAI_API_KEY

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY is not set in environment variables!")

client = OpenAI(api_key=OPENAI_API_KEY)


def premium_reasoning(question: str) -> str:
    """
    High-quality strategic reasoning for the /reason endpoint.
    """
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    prompt = f"""
You are a world-class strategic intelligence AI.

Analyze the following question with clarity, depth, and practical value.
Focus on key dynamics, risks, opportunities, second-order effects, and asymmetric opportunities.

Question: {question}

Structure your response exactly like this:

**Core Insight**
(1-2 powerful sentences that cut to the heart of the issue)

**Key Analysis**
(Deep reasoning covering the most important factors, trade-offs, risks, and opportunities)

**Recommended Action**
(Clear, practical recommendation — what the user should do or understand next)

Be concise yet comprehensive. Avoid fluff and corporate jargon.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a world-class strategic intelligence AI."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1200,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"OpenAI API error in premium_reasoning: {e}")
        raise RuntimeError("Reasoning engine temporarily unavailable. Please try again later.") from e


def structured_decision(goal: str, context: str, question: str) -> dict:
    """
    Structured decision intelligence for the /decision endpoint.
    Returns clean JSON with decision, confidence, reasoning, and risk_level.
    """
    if not all([goal.strip(), context.strip(), question.strip()]):
        raise ValueError("goal, context, and question are all required.")

    prompt = f"""
You are a strategic decision intelligence AI.

Goal: {goal}
Context: {context}
Question: {question}

Return ONLY valid JSON with this exact structure:
{{
  "decision": "short recommended action",
  "confidence": 0.XX,
  "reasoning": "clear explanation of why this is the best choice",
  "risk_level": "low|medium|high"
}}

Be objective, concise, and realistic in your assessment.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=800,
        )

        result_text = response.choices[0].message.content.strip()
        result_json = json.loads(result_text)

        # Basic validation of returned JSON
        required_keys = {"decision", "confidence", "reasoning", "risk_level"}
        if not required_keys.issubset(result_json.keys()):
            raise ValueError("Missing required keys in decision JSON")

        return result_json

    except json.JSONDecodeError:
        print("Decision engine returned invalid JSON")
        raise RuntimeError("Decision engine failed to return valid JSON")
    except Exception as e:
        print(f"OpenAI API error in structured_decision: {e}")
        raise RuntimeError("Decision engine temporarily unavailable. Please try again later.") from e


# =========================
# Quick Test
# =========================
if __name__ == "__main__":
    print("=== Testing premium_reasoning ===")
    test_q = "Should I increase my Bitcoin exposure right now given current market conditions?"
    print(premium_reasoning(test_q))

    print("\n=== Testing structured_decision ===")
    result = structured_decision(
        goal="Launch a new AI product",
        context="We have strong engineering talent but limited marketing budget. Competitor just raised $20M.",
        question="Should we launch in Q2 or delay to Q3?"
    )
    print(json.dumps(result, indent=2))
