# Installation guide for AI agents (Cline et al.)

This is a **remote, hosted** MCP server. There is nothing to install, build, clone, or run — you only
add a server entry pointing at the hosted URL. Do NOT try to npm-install or run a local process.

## Steps

1. Get a free API key (the user can do this; first calls are free):
   ```
   curl -s -X POST https://api.babyblueviper.com/register -d '{"label":"cline"}'
   ```
   The response contains `api_key`. Ask the user for their key, or have them register.

2. Add this server to the host's MCP settings as a **Streamable HTTP (remote)** server:
   - **URL:** `https://api.babyblueviper.com/mcp/verify`
   - **Transport / type:** `streamableHttp`
   - **Header:** `Authorization: Bearer <api_key>`

   **Cline CLI — one command (recommended, non-interactive):**
   ```bash
   cline mcp add invinoveritas https://api.babyblueviper.com/mcp/verify \
     --transport streamableHttp --header "Authorization: Bearer <api_key>" --yes
   ```

   **Cline (IDE) — or add the entry to `cline_mcp_settings.json`:**
   ```json
   {
     "mcpServers": {
       "invinoveritas": {
         "type": "streamableHttp",
         "url": "https://api.babyblueviper.com/mcp/verify",
         "headers": { "Authorization": "Bearer <api_key>" }
       }
     }
   }
   ```

3. Confirm it connected: the server should expose tools including `review` and `verify_proof`.
   `verify_proof` requires no auth, so you can call it to confirm connectivity even before funding the key.

## Notes

- `verify_proof` and `ledger` are free / no-auth. `review` is paid; new accounts include a few free calls. With no balance
  left, paid tools return a plain "not available with your current balance" message; that is expected, not an error.
- Clients with MCP OAuth support can skip the header: they are prompted to sign in on the first paid call.
- No environment variables, no local command, no Docker. If a setup flow asks for a command or args,
  this server does not use them — it is a URL (plus an Authorization header, or OAuth sign-in).
