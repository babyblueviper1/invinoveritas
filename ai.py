from openai import OpenAI
from config import OPENAI_API_KEY

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY is not set in environment variables!")

client = OpenAI(api_key=OPENAI_API_KEY)


def premium_reasoning(question: str) -> str:
    """
    High-quality paid reasoning.
    Returns well-structured, strategic intelligence.
    """

    prompt = f"""
You are a high-level strategic intelligence system specialized in clear thinking and decision-making.

Your responses must be:
- Deep and insightful (avoid generic advice)
- Well-structured and easy to read
- Action-oriented with practical conclusions

Answer the user's question using this exact structure:

**Core Insight**
(one or two sentences that cut to what really matters)

**Deep Reasoning**
(detailed analysis, key factors, risks, opportunities, second-order effects)

**Practical Conclusion**
(what the user should do or understand, with clear recommendation)

Question:
{question}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",           # Best balance of quality/speed/price
            # model="gpt-4o"               # Use this for higher quality (more expensive)
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
        raise HTTPException(500, "Reasoning engine temporarily unavailable") from e


# Optional: Keep a simple test function
if __name__ == "__main__":
    test_question = "Should I increase my Bitcoin exposure right now given current market conditions?"
    print(premium_reasoning(test_question))
