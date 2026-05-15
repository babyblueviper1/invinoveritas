# invinoveritas Activepieces Piece

NPM package: `invinoveritas-activepieces-piece`

This piece gives no-code builders direct access to invinoveritas:

- Premium reasoning
- Structured decisions
- Marketplace purchase
- Memory store/retrieve
- A2A discover, quote, and delegation
- Growth + PNL attack planning

Payments remain Bitcoin/Lightning-native. The piece uses Bearer API keys because automations need repeatable credentials; users fund those balances with sats over Lightning.


## Install Locally

```bash
cd integrations/activepieces/invinoveritas
npm install
npm run build
```

Then link/import the piece in an Activepieces development workspace following the Activepieces custom-piece workflow.

## Publish Checklist

1. Confirm actions compile against the target Activepieces framework version (`@activepieces/pieces-framework` 0.28.x).
2. Capture screenshots from `/dashboard`, `/marketplace`, and `/leaderboard`.
3. Submit to the Activepieces registry or publish the package under the approved namespace.
4. Verify revenue attribution in API logs via `X-Invino-Integration: activepieces`.

## Proof Copy

Standard Spawn Kit sold for 50,000 sats; seller payout was 47,500 sats; seller withdrew 7,000 sats over Lightning.

Use this proof in the listing description because no-code users need trust before funding automation balances.
