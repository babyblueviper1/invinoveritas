#!/usr/bin/env python3
"""Pin-update process for deils-anchor-v1 (review 3, Echo TG 5863: "PINNED_BITS only has epochs 481 and 482 ... the build needs a
pin-update process").

The expected difficulty (nBits) is constant within a retarget epoch (2016 blocks). For each epoch asked, this reads the header of the
epoch's FIRST block from two explorers you choose, requires them to return byte-identical headers, checks the header's proof of work
under its own bits, and writes {"epoch": bits} to a pins file. Pins are trusted input like headers: a verifier that runs this against
its own node instead of explorers removes the explorers from its trust set. check.py / ots_verify.py read the file with --pins.

  python3 pins.py 481 482 483 > pins.json                 # explicit epochs
  python3 pins.py --for-height 973231 > pins.json         # the epoch of one height
  python3 pins.py --self-test                              # offline: canned sources, agree / disagree / bad proof of work
Standard library only; network access needed (or edit SOURCES to your node's REST endpoint)."""
import hashlib, json, os, sys, urllib.request

SOURCES = [("mempool.space", "https://mempool.space/api/block-height/{h}", "https://mempool.space/api/block/{hash}/header"),
           ("blockstream.info", "https://blockstream.info/api/block-height/{h}", "https://blockstream.info/api/block/{hash}/header")]


def _get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read().decode().strip()


def header_at(h, get=None):
    get = get or _get
    got = []
    for name, hurl, hdr in SOURCES:
        bh = get(hurl.format(h=h)); got.append((name, get(hdr.format(hash=bh))))
    if len({x for _, x in got}) != 1:
        raise SystemExit(f"height {h}: sources disagree: {[(n, x[:16]) for n, x in got]}")
    return bytes.fromhex(got[0][1])


def bits_of(header):
    bits = int.from_bytes(header[72:76], "little")
    exp, mant = bits >> 24, bits & 0xFFFFFF
    target = mant << (8 * (exp - 3))
    if int.from_bytes(hashlib.sha256(hashlib.sha256(header).digest()).digest(), "little") > target:
        raise SystemExit("header fails its own proof of work")
    return bits


def self_test():
    """Offline (review 4, Echo TG 5880 point 3): canned sources serve the real header in ots/real.json. Two agreeing sources -> its
    bits; sources disagreeing -> refused; a header whose nonce is flipped (bad proof of work) -> refused."""
    real = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ots", "real.json")))
    h, hx = next(iter(real["headers"].items()))
    bad = hx[:-8] + ("%08x" % (int(hx[-8:], 16) ^ 1))
    def canned(a, b):
        def get(url):
            if "block-height" in url:
                return "blockhash"
            return a if "mempool" in url else b
        return get
    ok = 0
    want = int.from_bytes(bytes.fromhex(hx)[72:76], "little")
    got = bits_of(header_at(int(h), canned(hx, hx))); ok += got == want; print(("PASS" if got == want else "FAIL"), "two sources agree -> bits", hex(got))
    for name, g in (("sources disagree -> refused", canned(hx, bad)), ("bad proof of work -> refused", canned(bad, bad))):
        try:
            bits_of(header_at(int(h), g)); print("FAIL", name)
        except SystemExit:
            ok += 1; print("PASS", name)
    print(f"{ok}/3 pins self-test"); return 0 if ok == 3 else 1


def main(argv):
    if argv[:1] == ["--self-test"]:
        sys.exit(self_test())
    epochs = []
    if argv[:1] == ["--for-height"]:
        epochs = [int(argv[1]) // 2016]
    else:
        epochs = [int(a) for a in argv]
    if not epochs:
        raise SystemExit(__doc__)
    pins = {}
    for e in epochs:
        pins[str(e)] = bits_of(header_at(e * 2016))
        print(f"epoch {e}: bits 0x{pins[str(e)]:08x} (first block {e * 2016}, {' + '.join(n for n, *_ in SOURCES)} agree)", file=sys.stderr)
    json.dump(pins, sys.stdout, indent=1); print()


if __name__ == "__main__":
    main(sys.argv[1:])
