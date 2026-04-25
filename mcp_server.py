#!/usr/bin/env python3
"""
invinoveritas MCP stdio server.
Proxies stdio to the hosted MCP endpoint at https://api.babyblueviper.com/mcp
Requires: pip install mcp-proxy
Usage:    INVINO_API_KEY=ivv_... python mcp_server.py
"""
import os
import sys
import subprocess

api_key = os.environ.get("INVINO_API_KEY", "")
if not api_key:
    print("Error: INVINO_API_KEY environment variable is required.", file=sys.stderr)
    print("Get one at https://api.babyblueviper.com/register", file=sys.stderr)
    sys.exit(1)

subprocess.execvp("mcp-proxy", [
    "mcp-proxy",
    "--header", f"Authorization: Bearer {api_key}",
    "https://api.babyblueviper.com/mcp",
])
