from openai import OpenAI
from config import OPENAI_API_KEY
import os

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY is not set in environment variables!")

client = OpenAI(api_key=OPENAI_API_KEY)


def premium_reasoning(question: str) -> str:
    """
    High-quality strategic reasoning for the /reason endpoint.
    Returns clear, structured, and actionable intelligence.
    """

    prompt = f"""
You are a high-level strategic intelligence system.

Your goal is to deliver deep, clear thinking that helps a human or autonomous agent make a better decision.
Avoid generic answers. Focus on what actually matters.

Structure your response exactly like this:

**Core Insight**
(1-2 sentences that cut to the heart of the matter)

**Deep Reasoning**
(Detailed analysis, key factors, risks, opportunities, and second-order effects)

**Practical Conclusion**
(What the user should do or understand, with a clear recommendation)

Question:
{question}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",          # Fast + high quality
            messages=[
                {"role": "system", "content": "You are a world-class strategic intelligence AI."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1200,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"OpenAI API error: {e}")
        raise Exception("Reasoning engine temporarily unavailable") from e


# Optional: Simple test when
