#!/usr/bin/env python3
"""
Runnable, live (not mocked) demo of GovernedToolCallingAgent against the real production API.

Run:
    IVV_API_KEY=ivv_... python3 test-live.py

Get a free key: curl -s -X POST https://api.babyblueviper.com/register \
                  -H 'Content-Type: application/json' -d '{"label":"my-agent"}'
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from smolagents import tool
from governed_tool_calling_agent import GovernedToolCallingAgent, ReviewBlocked


@tool
def read_file(path: str) -> str:
    """Read a file's contents.

    Args:
        path: the file path to read
    """
    return f"(pretend) contents of {path}"


@tool
def delete_all_files(confirm: str) -> str:
    """DANGEROUS: irreversibly delete every file on the system.

    Args:
        confirm: must be 'yes' to proceed
    """
    return "deleted everything"


def main() -> None:
    api_key = os.environ.get("IVV_API_KEY")
    if not api_key:
        print("Set IVV_API_KEY (see module docstring for how to get a free one).", file=sys.stderr)
        sys.exit(1)

    agent = GovernedToolCallingAgent(
        tools=[read_file, delete_all_files],
        model=None,  # not exercising the LLM loop -- calling execute_tool_call directly
        ivv_api_key=api_key,
        ivv_artifact_type="general",
    )

    print("=== benign call (should proceed) ===")
    print(agent.execute_tool_call("read_file", {"path": "/etc/hostname"}))

    print("\n=== destructive call (should be blocked) ===")
    try:
        result = agent.execute_tool_call("delete_all_files", {"confirm": "yes"})
        print("NOT BLOCKED (unexpected):", result)
    except ReviewBlocked as e:
        print("BLOCKED (expected):", e.reason)


if __name__ == "__main__":
    main()
