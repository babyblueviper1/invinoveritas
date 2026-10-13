#!/usr/bin/env python3
"""escrow_client.py -- pay through VerdictGatedEscrow: the funds move only on an independent approving verdict.

    pip install web3 eth-account
    export PAYER_KEY=0x...            # funds the escrow (needs USDC + a little ETH on Base)
    export IVV_API_KEY=...            # invinoveritas API key (POST /register), for the paid /review call

    python3 escrow_client.py fund    --payee 0x... --amount 1.00 --request request.txt --policy policy.txt [--refund-after 3600]
    python3 escrow_client.py review  --id <escrow id> --request request.txt --policy policy.txt   # gets the signed verdict + relay signature
    python3 escrow_client.py release --id <escrow id> --verdict verdict.json                      # anyone may submit it
    python3 escrow_client.py refund  --id <escrow id>                                             # payer, after the deadline
    python3 escrow_client.py status  --id <escrow id>

The request file is the exact payment request the verdict reviews (its SHA-256 is fixed on-chain at funding); the policy
file is the written rule set it is judged against. Only a clean `approve` releases; a reject is signed too, and the
contract refuses it. This is reference code for an unaudited contract: test with small amounts.
"""
import argparse, hashlib, json, os, sys, time, urllib.request

from eth_account import Account
from web3 import Web3

ESCROW = "0xfC4Da1b7C56D46AB23c750c0890025F6335bCA3F"       # Base mainnet, verifier = invinoveritas published key
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
API = os.environ.get("IVV_API", "https://api.babyblueviper.com")
RPC = os.environ.get("BASE_RPC", "https://mainnet.base.org")
CHAIN_ID = 8453

ABI = [
    {"name": "fund", "type": "function", "stateMutability": "nonpayable", "outputs": [{"type": "uint256"}],
     "inputs": [{"name": "salt", "type": "bytes32"}, {"name": "payee", "type": "address"}, {"name": "amount", "type": "uint256"},
                {"name": "resultHash", "type": "bytes32"}, {"name": "tdHash", "type": "bytes32"}, {"name": "taskVersion", "type": "uint64"},
                {"name": "refundAfter", "type": "uint64"}]},
    {"name": "release", "type": "function", "stateMutability": "nonpayable", "outputs": [],
     "inputs": [{"name": "id", "type": "uint256"}, {"name": "submissionId", "type": "uint256"}, {"name": "decisionRef", "type": "bytes32"},
                {"name": "sig", "type": "bytes"}]},
    {"name": "refund", "type": "function", "stateMutability": "nonpayable", "outputs": [], "inputs": [{"name": "id", "type": "uint256"}]},
    {"name": "escrowId", "type": "function", "stateMutability": "pure", "outputs": [{"type": "uint256"}],
     "inputs": [{"name": "payer", "type": "address"}, {"name": "salt", "type": "bytes32"}]},
    {"name": "escrows", "type": "function", "stateMutability": "view", "inputs": [{"name": "", "type": "uint256"}],
     "outputs": [{"name": "payer", "type": "address"}, {"name": "payee", "type": "address"}, {"name": "amount", "type": "uint256"},
                 {"name": "resultHash", "type": "bytes32"}, {"name": "tdHash", "type": "bytes32"}, {"name": "taskVersion", "type": "uint64"},
                 {"name": "refundAfter", "type": "uint64"}, {"name": "state", "type": "uint8"}]},
]
ERC20 = [{"name": "approve", "type": "function", "stateMutability": "nonpayable", "outputs": [{"type": "bool"}],
          "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}]}]
STATES = ["none", "funded", "released", "refunded"]


def w3():
    return Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30, "headers": {"User-Agent": "verdict-escrow-client/1"}}))


def send(w, acct, fn):
    tx = fn.build_transaction({"from": acct.address, "nonce": w.eth.get_transaction_count(acct.address), "chainId": CHAIN_ID})
    h = w.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    r = w.eth.wait_for_transaction_receipt(h, timeout=180)
    print(json.dumps({"tx": "0x" + h.hex().removeprefix("0x"), "status": r.status, "block": r.blockNumber}))
    return r


def text(path):
    return open(path, encoding="utf-8").read()


def cmd_fund(a):
    w, acct = w3(), Account.from_key(os.environ["PAYER_KEY"])
    esc = w.eth.contract(Web3.to_checksum_address(ESCROW), abi=ABI)
    amount = int(round(float(a.amount) * 1_000_000))
    salt = hashlib.sha256(f"{acct.address}:{time.time()}".encode()).digest()
    eid = esc.functions.escrowId(acct.address, salt).call()
    send(w, acct, w.eth.contract(Web3.to_checksum_address(USDC), abi=ERC20).functions.approve(esc.address, amount))
    send(w, acct, esc.functions.fund(salt, Web3.to_checksum_address(a.payee), amount, hashlib.sha256(text(a.request).encode()).digest(),
                                     hashlib.sha256(text(a.policy).encode()).digest(), 1, int(time.time()) + int(a.refund_after)))
    print(json.dumps({"escrow_id": str(eid)}))


def cmd_review(a):
    request, policy = text(a.request), text(a.policy)
    body = {"artifact": request, "artifact_type": "general", "sign": True,
            "context": "Decide whether this payment request complies with the written payment policy (the task document): "
                       "approve only if it meets every policy item, reject if it fails any.",
            "verdict_relay": {"chain_id": CHAIN_ID, "authority": ESCROW, "task_contract": ESCROW, "token_id": str(a.id), "submission_id": 1,
                              "task_version": 1, "result_hash": "0x" + hashlib.sha256(request.encode()).hexdigest(), "task_document": policy}}
    if a.policy_json:          # optional policy-governed mode: deterministic checks first, evidential state per condition
        body.update(json.loads(text(a.policy_json)))
    req = urllib.request.Request(f"{API}/review", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['IVV_API_KEY']}"})
    rv = json.loads(urllib.request.urlopen(req, timeout=300).read())
    out = a.out or f"verdict_{a.id}.json"
    json.dump(rv, open(out, "w"), indent=1)
    relay = rv.get("verdict_relay") or {}
    print(json.dumps({"verdict": rv.get("verdict"), "summary": rv.get("summary"), "relay_issued": relay.get("issued"),
                      "approved": relay.get("approved"), "saved": out}))


def cmd_release(a):
    w = w3()
    acct = Account.from_key(os.environ.get("SUBMITTER_KEY") or os.environ["PAYER_KEY"])
    relay = json.load(open(a.verdict)).get("verdict_relay") or {}
    if not (relay.get("issued") and relay.get("approved")):
        sys.exit("this verdict is not a signed approval; the contract would refuse it")
    esc = w.eth.contract(Web3.to_checksum_address(ESCROW), abi=ABI)
    send(w, acct, esc.functions.release(int(a.id), 1, bytes.fromhex(relay["decision_ref"][2:]), bytes.fromhex(relay["signature"][2:])))


def cmd_refund(a):
    w, acct = w3(), Account.from_key(os.environ["PAYER_KEY"])
    send(w, acct, w.eth.contract(Web3.to_checksum_address(ESCROW), abi=ABI).functions.refund(int(a.id)))


def cmd_status(a):
    e = w3().eth.contract(Web3.to_checksum_address(ESCROW), abi=ABI).functions.escrows(int(a.id)).call()
    print(json.dumps({"payer": e[0], "payee": e[1], "amount_usdc": e[2] / 1e6, "request_sha256": e[3].hex(), "policy_sha256": e[4].hex(),
                      "refund_after": e[6], "state": STATES[e[7]]}))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fund"); f.add_argument("--payee", required=True); f.add_argument("--amount", required=True)
    f.add_argument("--request", required=True); f.add_argument("--policy", required=True); f.add_argument("--refund-after", default=3600)
    r = sub.add_parser("review"); r.add_argument("--id", required=True); r.add_argument("--request", required=True); r.add_argument("--policy", required=True)
    r.add_argument("--policy-json", help="optional JSON file with {policy, facts, evidence} for the policy-governed mode"); r.add_argument("--out")
    rl = sub.add_parser("release"); rl.add_argument("--id", required=True); rl.add_argument("--verdict", required=True)
    rf = sub.add_parser("refund"); rf.add_argument("--id", required=True)
    s = sub.add_parser("status"); s.add_argument("--id", required=True)
    a = p.parse_args()
    {"fund": cmd_fund, "review": cmd_review, "release": cmd_release, "refund": cmd_refund, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
