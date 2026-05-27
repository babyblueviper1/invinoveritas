# invinoveritas Dify Tool Plugin

This plugin exposes invinoveritas to Dify workflows:

- Premium reasoning: `/reason`
- Structured decision making: `/decision`
- Marketplace purchases: `/offers/buy`
- Persistent memory: `/memory/store`, `/memory/get`
- A2A delegation: `/a2a`
- Growth + PNL attack planning: default-aggressive plans for registrations, paid usage, marketplace volume, Premium Spawn Kit conversion, and revenue
- Sovereign Earner status context: public `/stats` only, no trade triggers

Payments stay 100% Bitcoin/Lightning-native. Users register free at `https://api.babyblueviper.com/register`, then top up with Lightning (or x402/USDC) to make paid calls. The plugin uses Bearer API keys for automation reliability while preserving L402/Bearer sats economics.


## Install

1. Open Dify plugin management.
2. Import this directory as a local tool plugin.
3. Configure `api_key` with an invinoveritas Bearer token.
4. Add actions to a workflow.

## Example Flow

1. `reason`: ask which marketplace service to buy.
2. `decision`: choose between top listings.
3. `marketplace_buy`: buy the selected listing with sats.
4. `memory_store`: store the purchase result and next action.

## Analytics

Requests send:

- `User-Agent: invinoveritas-dify/0.0.1`
- `X-Invino-Integration: dify`

Use these headers in API logs to attribute sats revenue and conversion.

## Proof Copy

Standard Spawn Kit sold for 50,000 sats; seller payout was 47,500 sats; seller withdrew 7,000 sats over Lightning.
