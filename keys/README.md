# invinoveritas signing key

`governance-pubkey.json` is a snapshot of https://api.babyblueviper.com/governance/pubkey, published here so a verifier can pin our key from a host other than the one serving the records.

Active key (BIP-340 Schnorr x-only, signs the NIP-01 event id of every verdict proof and DEILS commitment record):

    6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7

If this file and the live manifest ever disagree, treat that as a key-integrity failure. Any rotation or revocation will be committed here in the same change that updates the live manifest.
