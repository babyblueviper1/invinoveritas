from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)


def premium_reasoning(question):
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=f"""
You are a strategic intelligence AI.

Give a high-level, structured, clear and deep answer to:

{question}
"""
    )

    return response.output_text
