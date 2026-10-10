"""python3 -m l402_verdict_gate.verify receipt.json [--pubkey HEX]  -- offline, standard library only. Exit 0 iff valid."""
import json
import sys

from .receipt import verify_receipt


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    pub = None
    if "--pubkey" in argv:
        i = argv.index("--pubkey")
        pub = argv[i + 1]
        del argv[i:i + 2]
    with open(argv[0]) as f:
        r = verify_receipt(json.load(f), pubkey=pub)
    for k, v in r["checks"].items():
        print(f"{'ok  ' if v else 'FAIL'} {k}")
    if r.get("error"):
        print(r["error"])
    print("VALID" if r["valid"] else "INVALID")
    return 0 if r["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
