from typing import Dict, Any, Optional, Callable, Awaitable
try:
    from .client import InvinoClient, AsyncInvinoClient
except ImportError:
    from invinoveritas import InvinoClient, AsyncInvinoClient


# =========================
# DECISION LOGIC
# =========================

def should_call_invinoveritas(task: Dict[str, Any]) -> bool:
    """
    Determine whether to call invinoveritas based on task complexity and impact.
    """
    return any([
        task.get("steps", 1) > 2,
        task.get("uncertainty", 0) > 0.6,
        task.get("value_at_risk", 0) > 100,
        task.get("requires_reasoning", False)
    ])


# =========================
# SYNC METHODS
# =========================

def smart_reason(
    task: Dict[str, Any],
    client: Optional[InvinoClient] = None,
    fallback: Optional[Callable[[Dict[str, Any]], Any]] = None
):
    """
    Conditionally call invinoveritas.reason() when needed.

    Returns:
    - InvinoResponse OR fallback result
    """
    if client is None:
        client = InvinoClient()

    if should_call_invinoveritas(task):
        return client.reason(task["question"])

    if fallback:
        return fallback(task)

    return {"answer": "fallback or local reasoning"}


def smart_decide(
    task: Dict[str, Any],
    client: Optional[InvinoClient] = None,
    fallback: Optional[Callable[[Dict[str, Any]], Any]] = None
):
    """
    Conditionally call invinoveritas.decide() when needed.

    Expected task keys:
    - goal
    - question
    - context (optional)
    """
    if client is None:
        client = InvinoClient()

    if should_call_invinoveritas(task):
        return client.decide(
            goal=task["goal"],
            question=task["question"],
            context=task.get("context", "")
        )

    if fallback:
        return fallback(task)

    return {
        "decision": "fallback decision",
        "confidence": 0.5,
        "reasoning": "Used local fallback",
        "risk_level": "unknown"
    }


# =========================
# ASYNC METHODS
# =========================

async def async_smart_reason(
    task: Dict[str, Any],
    client: Optional[AsyncInvinoClient] = None,
    fallback: Optional[Callable[[Dict[str, Any]], Awaitable[Any]]] = None
):
    """
    Async version of smart_reason.
    """
    if client is None:
        client = AsyncInvinoClient()

    if should_call_invinoveritas(task):
        async with client:
            return await client.reason(task["question"])

    if fallback:
        return await fallback(task)

    return {"answer": "fallback or local reasoning"}


async def async_smart_decide(
    task: Dict[str, Any],
    client: Optional[AsyncInvinoClient] = None,
    fallback: Optional[Callable[[Dict[str, Any]], Awaitable[Any]]] = None
):
    """
    Async version of smart_decide.
    """
    if client is None:
        client = AsyncInvinoClient()

    if should_call_invinoveritas(task):
        async with client:
            return await client.decide(
                goal=task["goal"],
                question=task["question"],
                context=task.get("context", "")
            )

    if fallback:
        return await fallback(task)

    return {
        "decision": "fallback decision",
        "confidence": 0.5,
        "reasoning": "Used local fallback",
        "risk_level": "unknown"
    }
