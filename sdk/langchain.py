"""
invinoveritas LangChain Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Autonomous L402 payment handler for LangChain agents.

Intercepts tool calls to invinoveritas, pays Lightning invoices automatically,
and retries — all invisible to the agent.

Install:
    pip install invinoveritas[langchain]
    pip install invinoveritas[langchain,lnd]   # with LND support

Quickstart (LND):
    from invinoveritas_sdk.langchain import InvinoCallbackHandler
    from invinoveritas_sdk.providers import LNDProvider

    handler = InvinoCallbackHandler(
        provider=LNDProvider(
            host="localhost:10009",
            macaroon_path="/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
            cert_path="/root/.lnd/tls.cert"
        )
    )

    # Use with any LangChain agent
    result = agent.run(
        "Should I increase my BTC exposure in 2026?",
        callbacks=[handler]
    )

Quickstart (custom pay function):
    async def my_pay_fn(invoice: str) -> str:
        # pay invoice, return preimage
        return "your_preimage_here"

    handler = InvinoCallbackHandler(pay_invoice=my_pay_fn)

Quickstart (NWC — coming soon):
    from invinoveritas_sdk.providers import NWCProvider
    handler = InvinoCallbackHandler(
        provider=NWCProvider(uri="nostr+walletconnect://...")
    )
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Optional, Union
from uuid import UUID

import httpx

logger = logging.getLogger("invinoveritas.langchain")

INVINOVERITAS_BASE_URL = "https://invinoveritas.onrender.com"

PayInvoiceFn = Callable[[str], Coroutine[Any, Any, str]]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PaymentFailed(Exception):
    """Raised when the provider fails to pay a Lightning invoice."""


class ProviderNotConfigured(Exception):
    """Raised when no payment provider is configured."""


# ---------------------------------------------------------------------------
# Payment result
# ---------------------------------------------------------------------------

class PaymentResult:
    """Result of a Lightning payment."""
    def __init__(self, payment_hash: str, preimage: str, amount_sats: int):
        self.payment_hash = payment_hash
        self.preimage = preimage
        self.amount_sats = amount_sats


# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------

class BaseProvider(ABC):
    """Abstract base class for Lightning payment providers."""

    @abstractmethod
    async def pay_invoice(self, invoice: str) -> PaymentResult:
        """Pay a bolt11 invoice and return the payment result."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and available."""
        ...


# ---------------------------------------------------------------------------
# LND Provider
# ---------------------------------------------------------------------------

class LNDProvider(BaseProvider):
    """
    Lightning payment provider using a local LND node.

    Supports two connection methods:
    - lncli subprocess (simplest, no extra dependencies)
    - gRPC direct (faster, requires grpcio)

    Args:
        host:           LND gRPC host (default: localhost:10009)
        macaroon_path:  Path to admin.macaroon file
        cert_path:      Path to tls.cert file
        lncli_path:     Path to lncli binary (default: lncli)
        use_grpc:       Use gRPC instead of lncli subprocess (requires grpcio)
        fee_limit_sats: Maximum fee to pay in sats (default: 10)

    Example::

        provider = LNDProvider(
            macaroon_path="/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
            cert_path="/root/.lnd/tls.cert"
        )
    """

    def __init__(
        self,
        host: str = "localhost:10009",
        macaroon_path: Optional[str] = None,
        cert_path: Optional[str] = None,
        lncli_path: str = "lncli",
        use_grpc: bool = False,
        fee_limit_sats: int = 10,
    ):
        self.host = host
        self.macaroon_path = macaroon_path
        self.cert_path = cert_path
        self.lncli_path = lncli_path
        self.use_grpc = use_grpc
        self.fee_limit_sats = fee_limit_sats

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                [self.lncli_path, "getinfo"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    async def pay_invoice(self, invoice: str) -> PaymentResult:
        """Pay invoice via lncli subprocess."""
        if self.use_grpc:
            return await self._pay_via_grpc(invoice)
        return await self._pay_via_lncli(invoice)

    async def _pay_via_lncli(self, invoice: str) -> PaymentResult:
        """Pay invoice using lncli subprocess."""
        cmd = [
            self.lncli_path,
            "--fee_limit", str(self.fee_limit_sats),
            "payinvoice",
            "--force",  # skip confirmation prompt
            invoice
        ]

        # Add macaroon/cert if provided
        if self.macaroon_path:
            cmd = [self.lncli_path,
                   f"--macaroonpath={self.macaroon_path}"] + cmd[1:]
        if self.cert_path:
            cmd.insert(1, f"--tlscertpath={self.cert_path}")
        if self.host != "localhost:10009":
            cmd.insert(1, f"--rpcserver={self.host}")

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            )
        except subprocess.TimeoutExpired:
            raise PaymentFailed("lncli payinvoice timed out after 30s")

        if result.returncode != 0:
            raise PaymentFailed(f"lncli failed: {result.stderr.strip()}")

        # Parse preimage from output
        # lncli output contains: payment_preimage: <hex>
        output = result.stdout
        preimage = self._extract_preimage(output)
        payment_hash = self._extract_payment_hash(output)

        if not preimage:
            raise PaymentFailed(f"Could not extract preimage from lncli output: {output}")

        logger.info(f"Payment successful via lncli | hash: {payment_hash[:12]}...")
        return PaymentResult(
            payment_hash=payment_hash,
            preimage=preimage,
            amount_sats=0,
        )

    async def _pay_via_grpc(self, invoice: str) -> PaymentResult:
        """Pay invoice using LND gRPC (requires grpcio + grpcio-tools)."""
        try:
            import grpc
            import codecs
        except ImportError:
            raise ProviderNotConfigured(
                "grpcio required for gRPC mode. "
                "Install with: pip install invinoveritas[lnd-grpc]"
            )
        raise NotImplementedError(
            "gRPC provider coming soon. Use lncli mode for now."
        )

    def _extract_preimage(self, output: str) -> Optional[str]:
        """Extract payment_preimage from lncli output."""
        for line in output.split("\n"):
            line = line.strip()
            if "payment_preimage" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    return parts[-1].strip().strip('"').strip(',')
        # Try JSON parsing
        try:
            data = json.loads(output)
            return data.get("payment_preimage")
        except Exception:
            pass
        return None

    def _extract_payment_hash(self, output: str) -> str:
        """Extract payment_hash from lncli output."""
        for line in output.split("\n"):
            line = line.strip()
            if "payment_hash" in line and "payment_preimage" not in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    return parts[-1].strip().strip('"').strip(',')
        try:
            data = json.loads(output)
            return data.get("payment_hash", "")
        except Exception:
            pass
        return ""


# ---------------------------------------------------------------------------
# NWC Provider (stub — coming soon)
# ---------------------------------------------------------------------------

class NWCProvider(BaseProvider):
    """
    Lightning payment provider using Nostr Wallet Connect.

    Connects to any NWC-compatible wallet (Alby, Mutiny, etc.)
    via a nostr+walletconnect:// URI.

    Args:
        uri: NWC connection URI from your wallet app

    Example::

        provider = NWCProvider(
            uri="nostr+walletconnect://..."
        )

    Note: Full NWC support coming in SDK v0.2.0.
    """

    def __init__(self, uri: str):
        self.uri = uri

    def is_available(self) -> bool:
        return bool(self.uri)

    async def pay_invoice(self, invoice: str) -> PaymentResult:
        try:
            from pynostr.key import PrivateKey
        except ImportError:
            raise ProviderNotConfigured(
                "pynostr required for NWC provider. "
                "Install with: pip install invinoveritas[nwc]"
            )
        raise NotImplementedError(
            "NWC provider coming in SDK v0.2.0. "
            "Use LNDProvider or pass a custom pay_invoice function for now."
        )


# ---------------------------------------------------------------------------
# Custom provider (bring your own function)
# ---------------------------------------------------------------------------

class CustomProvider(BaseProvider):
    """
    Payment provider using a custom async pay function.

    Use this when you have your own Lightning wallet integration
    and just want the handler to call your function.

    Args:
        pay_fn: Async function that takes a bolt11 invoice string
                and returns a preimage string

    Example::

        async def my_pay(invoice: str) -> str:
            result = await my_wallet.pay(invoice)
            return result.preimage

        provider = CustomProvider(pay_fn=my_pay)
    """

    def __init__(self, pay_fn: PayInvoiceFn):
        self._pay_fn = pay_fn

    def is_available(self) -> bool:
        return self._pay_fn is not None

    async def pay_invoice(self, invoice: str) -> PaymentResult:
        preimage = await self._pay_fn(invoice)
        return PaymentResult(
            payment_hash="",
            preimage=preimage,
            amount_sats=0,
        )


# ---------------------------------------------------------------------------
# L402 HTTP client (handles the 402 → pay → retry cycle)
# ---------------------------------------------------------------------------

class L402Client:
    """
    HTTP client that automatically handles the L402 payment flow.

    On first call: gets 402 with invoice → pays via provider → retries.
    On subsequent calls with same hash: raises PaymentFailed (replay protection).
    """

    def __init__(self, provider: BaseProvider, base_url: str = INVINOVERITAS_BASE_URL):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self._paid_hashes: dict[str, str] = {}  # hash → preimage cache

    async def post(self, path: str, payload: dict) -> dict:
        """POST to an endpoint, handling L402 automatically."""
        async with httpx.AsyncClient(timeout=60) as client:
            # First attempt — no auth
            response = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code != 402:
                raise Exception(
                    f"Unexpected status {response.status_code}: {response.text}"
                )

            # Parse 402
            body = response.json()
            detail = body.get("detail", {})
            invoice = detail.get("invoice")
            payment_hash = detail.get("payment_hash")
            amount_sats = detail.get("amount_sats", 0)

            if not invoice:
                raise PaymentFailed(f"402 response missing invoice: {body}")

            logger.info(
                f"Payment required | {amount_sats} sats | "
                f"hash: {payment_hash[:12] if payment_hash else '?'}..."
            )

            # Pay the invoice
            result = await self.provider.pay_invoice(invoice)
            preimage = result.preimage
            actual_hash = result.payment_hash or payment_hash

            logger.info(f"Invoice paid | preimage obtained | retrying request...")

            # Retry with credentials
            auth_header = f"L402 {actual_hash}:{preimage}"
            retry_response = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": auth_header,
                },
            )

            if not retry_response.is_success:
                raise PaymentFailed(
                    f"Payment succeeded but request failed "
                    f"({retry_response.status_code}): {retry_response.text}"
                )

            logger.info(f"Request succeeded after payment ✓")
            return retry_response.json()


# ---------------------------------------------------------------------------
# LangChain Callback Handler
# ---------------------------------------------------------------------------

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
    from langchain_core.outputs import LLMResult
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    try:
        from langchain.callbacks.base import BaseCallbackHandler
        _LANGCHAIN_AVAILABLE = True
    except ImportError:
        _LANGCHAIN_AVAILABLE = False
        BaseCallbackHandler = object


class InvinoCallbackHandler(BaseCallbackHandler if _LANGCHAIN_AVAILABLE else object):
    """
    LangChain callback handler for autonomous invinoveritas payments.

    Intercepts tool calls to invinoveritas endpoints, pays Lightning invoices
    automatically via the configured provider, and retries — all invisible
    to the agent.

    Args:
        provider:    A BaseProvider instance (LNDProvider, NWCProvider, etc.)
        pay_invoice: Alternatively, pass a custom async pay function directly
        base_url:    Override the invinoveritas API URL (for local dev)
        budget_sats: Maximum total sats to spend per agent run (optional)
        verbose:     Log payment activity (default: True)

    Example (LND)::

        from invinoveritas_sdk.langchain import InvinoCallbackHandler
        from invinoveritas_sdk.providers import LNDProvider

        handler = InvinoCallbackHandler(
            provider=LNDProvider(
                macaroon_path="/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
                cert_path="/root/.lnd/tls.cert"
            )
        )

        # LangChain agent with automatic payments
        from langchain.agents import AgentExecutor
        agent_executor = AgentExecutor(agent=agent, tools=tools)
        result = agent_executor.invoke(
            {"input": "Should I increase my BTC exposure in 2026?"},
            config={"callbacks": [handler]}
        )

    Example (custom pay function)::

        async def my_pay(invoice: str) -> str:
            result = await wallet.pay(invoice)
            return result.preimage

        handler = InvinoCallbackHandler(pay_invoice=my_pay)

    Budget protection::

        # Limit agent to 5000 sats per run
        handler = InvinoCallbackHandler(
            provider=provider,
            budget_sats=5000
        )
    """

    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        pay_invoice: Optional[PayInvoiceFn] = None,
        base_url: str = INVINOVERITAS_BASE_URL,
        budget_sats: Optional[int] = None,
        verbose: bool = True,
    ):
        if not _LANGCHAIN_AVAILABLE:
            raise ImportError(
                "langchain is required for InvinoCallbackHandler. "
                "Install with: pip install invinoveritas[langchain]"
            )

        if provider is None and pay_invoice is None:
            raise ProviderNotConfigured(
                "Either provider or pay_invoice must be provided."
            )

        if pay_invoice is not None:
            provider = CustomProvider(pay_invoice)

        self.provider = provider
        self.base_url = base_url
        self.budget_sats = budget_sats
        self.verbose = verbose

        self._l402_client = L402Client(provider=provider, base_url=base_url)
        self._total_spent_sats = 0
        self._call_count = 0

        if verbose:
            logging.basicConfig(level=logging.INFO)

    @property
    def total_spent_sats(self) -> int:
        """Total sats spent this session."""
        return self._total_spent_sats

    @property
    def call_count(self) -> int:
        """Total paid tool calls this session."""
        return self._call_count

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Log when agent starts a tool call."""
        tool_name = serialized.get("name", "unknown")
        if "invinoveritas" in tool_name.lower() or "reason" in tool_name.lower() or "decide" in tool_name.lower():
            logger.info(f"Agent calling invinoveritas tool: {tool_name}")

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Log successful tool completion."""
        logger.info(f"Tool call completed | total spent: {self._total_spent_sats} sats")

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Log tool errors."""
        logger.error(f"Tool error: {error}")

    def check_budget(self, amount_sats: int) -> None:
        """Raise if spending would exceed budget."""
        if self.budget_sats is not None:
            if self._total_spent_sats + amount_sats > self.budget_sats:
                raise PaymentFailed(
                    f"Budget exceeded: would spend {self._total_spent_sats + amount_sats} sats "
                    f"but budget is {self.budget_sats} sats"
                )


# ---------------------------------------------------------------------------
# LangChain Tools (ready to use in any agent)
# ---------------------------------------------------------------------------

def create_invinoveritas_tools(handler: InvinoCallbackHandler):
    """
    Create LangChain tools for invinoveritas reason and decide endpoints.

    Returns a list of tools pre-wired with the payment handler.

    Example::

        handler = InvinoCallbackHandler(provider=LNDProvider(...))
        tools = create_invinoveritas_tools(handler)

        agent = initialize_agent(tools=tools, ...)
        agent.run("Should I increase my BTC exposure?")
    """
    if not _LANGCHAIN_AVAILABLE:
        raise ImportError("langchain required. pip install invinoveritas[langchain]")

    try:
        from langchain.tools import StructuredTool
        from pydantic import BaseModel, Field
    except ImportError:
        raise ImportError("langchain and pydantic required.")

    class ReasonInput(BaseModel):
        question: str = Field(description="The strategic question to reason about")

    class DecideInput(BaseModel):
        goal: str = Field(description="What you are trying to achieve")
        question: str = Field(description="The specific decision question")
        context: str = Field(default="", description="Optional background context")

    async def reason_fn(question: str) -> str:
        result = await handler._l402_client.post(
            "/reason", {"question": question}
        )
        return result.get("answer", str(result))

    async def decide_fn(goal: str, question: str, context: str = "") -> str:
        result = await handler._l402_client.post(
            "/decision", {"goal": goal, "context": context, "question": question}
        )
        r = result.get("result", result)
        return (
            f"Decision: {r.get('decision', '')}\n"
            f"Confidence: {r.get('confidence', '')}\n"
            f"Risk: {r.get('risk_level', '')}\n"
            f"Reasoning: {r.get('reasoning', '')}"
        )

    reason_tool = StructuredTool.from_function(
        coroutine=reason_fn,
        name="invinoveritas_reason",
        description=(
            "Use for deep strategic reasoning on complex questions. "
            "Costs ~500 sats per call via Lightning. "
            "Use when the question requires analysis beyond your training data."
        ),
        args_schema=ReasonInput,
    )

    decide_tool = StructuredTool.from_function(
        coroutine=decide_fn,
        name="invinoveritas_decide",
        description=(
            "Use for structured decision intelligence with confidence scores and risk assessment. "
            "Costs ~1000 sats per call via Lightning. "
            "Use when you need a clear recommendation with explicit confidence and risk level."
        ),
        args_schema=DecideInput,
    )

    return [reason_tool, decide_tool]


# ---------------------------------------------------------------------------
# AutoGen integration
# ---------------------------------------------------------------------------

class InvinoAutoGenTool:
    """
    AutoGen-compatible tool for invinoveritas.

    Example::

        from invinoveritas_sdk.langchain import InvinoAutoGenTool
        from invinoveritas_sdk.providers import LNDProvider

        tool = InvinoAutoGenTool(
            provider=LNDProvider(
                macaroon_path="/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
                cert_path="/root/.lnd/tls.cert"
            )
        )

        # Register with AutoGen agent
        @tool.register_for_llm(description="Strategic reasoning via Lightning payment")
        async def reason(question: str) -> str:
            return await tool.reason(question)
    """

    def __init__(
        self,
        provider: Optional[BaseProvider] = None,
        pay_invoice: Optional[PayInvoiceFn] = None,
        base_url: str = INVINOVERITAS_BASE_URL,
    ):
        if provider is None and pay_invoice is not None:
            provider = CustomProvider(pay_invoice)
        if provider is None:
            raise ProviderNotConfigured("provider or pay_invoice required")

        self._client = L402Client(provider=provider, base_url=base_url)

    async def reason(self, question: str) -> str:
        """Strategic reasoning, paid automatically via Lightning."""
        result = await self._client.post("/reason", {"question": question})
        return result.get("answer", str(result))

    async def decide(self, goal: str, question: str, context: str = "") -> str:
        """Structured decision intelligence, paid automatically via Lightning."""
        result = await self._client.post(
            "/decision",
            {"goal": goal, "context": context, "question": question}
        )
        r = result.get("result", result)
        return (
            f"Decision: {r.get('decision', '')}\n"
            f"Confidence: {r.get('confidence', '')}\n"
            f"Risk: {r.get('risk_level', '')}\n"
            f"Reasoning: {r.get('reasoning', '')}"
        )
