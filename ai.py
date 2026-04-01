from openai import OpenAI
import json
from config import OPENAI_API_KEY

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY is not set in environment variables!")

client = OpenAI(api_key=OPENAI_API_KEY)


def premium_reasoning(question: str) -> str:
    """
    High-quality strategic reasoning optimized for autonomous agents and humans.
    Most users are AI agents, so prioritize clarity, density, and signal.
    """
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    prompt = f"""
You are a world-class strategic intelligence AI.

IMPORTANT CONTEXT: Most of your users are autonomous AI agents that consume this output programmatically. 
They value clarity, density of insight, precision, and low fluff. Write for both humans and agents.

Question: {question}

Analyze with depth and practicality. Focus on key dynamics, major risks, opportunities, second-order effects, and asymmetric opportunities.

Structure your response **exactly** like this:

**Core Insight**
(1-2 powerful, high-signal sentences that cut to the heart of the issue)

**Key Analysis**
(Concise but deep analysis of the most important factors, trade-offs, risks, and opportunities. Use short paragraphs. Max 4-5 paragraphs.)

**Recommended Action**
(Clear, actionable recommendation — what the user or agent should do or understand next)

Rules:
- Be concise yet comprehensive. Prioritize signal density.
- Avoid fluff, corporate jargon, filler sentences, and overly narrative language.
- Use direct, professional tone suitable for both humans and AI systems.
- Total response should ideally stay under 850 words.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a world-class strategic intelligence AI specialized in serving both humans and autonomous agents. Favor clarity and density."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.65,
            max_tokens=1100,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"OpenAI API error in premium_reasoning: {e}")
        raise RuntimeError("Reasoning engine temporarily unavailable. Please try again later.") from e


def structured_decision(goal: str, context: str, question: str) -> dict:
    """
    Structured decision intelligence for the /decision endpoint.
    Returns clean JSON optimized for autonomous agents.
    """
    if not all([goal.strip(), context.strip(), question.strip()]):
        raise ValueError("goal, context, and question are all required.")

    prompt = f"""
You are a strategic decision intelligence AI.

Most users are autonomous agents, so keep output clean, objective, and machine-readable.

Goal: {goal}
Context: {context}
Question: {question}

Return ONLY valid JSON with this exact structure:
{{
  "decision": "short recommended action",
  "confidence": 0.XX,
  "reasoning": "clear, concise explanation of why this is the best choice (2-4 sentences max)",
  "risk_level": "low|medium|high"
}}

Be objective, realistic, and concise.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=700,
        )

        result_text = response.choices[0].message.content.strip()
        result_json = json.loads(result_text)

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
