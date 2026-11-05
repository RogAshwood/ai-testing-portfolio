"""
validate_conversations.py: checks the M5 golden conversations against the test basis.

Test basis: datasets/chatbot_spec.md, the policy documents (01 to 09 plus the
M5 version of document 10) and datasets/claim_status.csv. Oracle:
datasets/conversations_golden.json. Same role as validate_golden.py on Day 3:
check the oracle before any model is run.

Checks:
  1. Structure: required fields, unique conv_id, stretch flag matches the ID
     prefix (S), known fault, known tool names, judge checks defined, rule IDs
     exist in the spec. A tool is in at most one of required_tools,
     forbidden_tools and unexpected_tools.
  2. Members and claims: every member exists; every claim ID passed to a claim
     tool is in standard form and belongs to that conversation's member.
  3. Claim IDs typed by the member (R3, R6):
       standard and the member's own   -> no constraint;
       standard, not theirs or unknown -> not passed to a claim tool, and the
                                          turn expects "can't find that claim"
                                          or forbids claim tools;
       malformed but recognisable      -> claim tools forbidden on that turn and
                                          the tidied ID is a key fact.
  4. Traceability: every key fact (any one of its 'a|b' alternatives) appears
     in at least one of the turn's fact_sources. claim:X must be the member's.
  5. No contradiction: no key fact alternative is also an absent term.
  6. not_in_corpus terms appear in no policy document.
  7. Fingerprints (sha256, first 12 characters) of every input are printed.

Usage:  python datasets/validate_conversations.py
Exit code 0 when all checks pass, 1 otherwise.

Change history:
  2026-11-04  v1  first version (M5), with unexpected_tools (soft) beside
                  forbidden_tools (hard).
"""
from __future__ import annotations
import csv, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "datasets"
GOLDEN = DATA / "conversations_golden.json"
SPEC = DATA / "chatbot_spec.md"
STATUS = DATA / "claim_status.csv"
DAY3_DOCS = DATA / "policy_docs"
M5_DOCS = DATA / "chatbot_docs"

TOOLS = {"search_policy", "get_claim_status", "list_my_claims", "request_callback"}
CLAIM_TOOLS = {"get_claim_status", "list_my_claims"}
FAULTS = {None, "claims_store_unavailable"}
STANDARD = re.compile(r"^HLH-\d{3}$")
TYPED_ID = re.compile(r"\b(?:HLH|HL|LH)[\s-]?\d{1,3}\b", re.IGNORECASE)


def norm(text: str) -> str:
    return " ".join(text.replace("**", "").replace("’", "'").lower().split())


def tidy_id(raw: str) -> str | None:
    """R6b: tidy a recognisable ID to HLH-NNN, or None if not recognisable."""
    m = re.fullmatch(r"(HLH|HL|LH)?(\d{1,3})", re.sub(r"[\s-]", "", raw.upper()))
    return f"HLH-{int(m.group(2)):03d}" if m else None


def corpus() -> dict[str, str]:
    docs = {p.stem: p.read_text(encoding="utf-8") for p in sorted(DAY3_DOCS.glob("*.md"))}
    for p in sorted(M5_DOCS.glob("*.md")):      # M5 overrides, e.g. document 10
        docs[p.stem] = p.read_text(encoding="utf-8")
    return docs


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> int:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    spec = SPEC.read_text(encoding="utf-8")
    claims = {r["claim_id"]: r for r in csv.DictReader(STATUS.open(encoding="utf-8"))}
    members = {r["member_id"] for r in claims.values()}
    docs = corpus()
    spec_rules = set(re.findall(r"\*\*(R\d+[a-c]?)\.\*\*", spec))
    judge_defs = set(golden.get("judge_checks", {}))
    errors: list[str] = []
    seen = set()

    for c in golden["conversations"]:
        cid, mid = c["conv_id"], c["member_id"]
        e = lambda msg, t=None: errors.append(f"{cid}{'' if t is None else f' turn {t}'}: {msg}")
        if cid in seen: e("duplicate conv_id")
        seen.add(cid)
        if c["stretch"] != cid.startswith("S"): e("stretch flag does not match ID prefix")
        if c.get("fault") not in FAULTS: e(f"unknown fault {c.get('fault')!r}")
        if mid not in members: e(f"unknown member {mid}"); continue
        for f in ("category", "scenario", "expected_outcome", "turns"):
            if not c.get(f): e(f"missing {f}")

        for i, t in enumerate(c["turns"], 1):
            required = {x["name"]: x["args"] for x in t["required_tools"]}
            forbidden, unexpected = set(t["forbidden_tools"]), set(t["unexpected_tools"])
            for name in set(required) | forbidden | unexpected:
                if name not in TOOLS: e(f"unknown tool {name}", i)
            if set(required) & forbidden: e("tool both required and forbidden", i)
            if set(required) & unexpected: e("tool both required and unexpected", i)
            if forbidden & unexpected: e("tool both forbidden and unexpected", i)
            if "request_callback" in required and not c["stretch"]: e("callback tool outside a stretch conversation", i)
            for r in t["rules"]:
                if r not in spec_rules: e(f"rule {r} not in spec", i)
            for j in t["judge_checks"]:
                if j not in judge_defs: e(f"judge check {j} not defined", i)

            # 2. claim tool arguments
            arg_id = (required.get("get_claim_status") or {}).get("claim_id")
            if arg_id:
                if not STANDARD.match(arg_id): e(f"tool argument {arg_id} not in standard form", i)
                elif arg_id not in claims or claims[arg_id]["member_id"] != mid:
                    e(f"tool expected to return {arg_id}, which is not this member's claim", i)

            # 3. IDs the member typed
            key_norm = [norm(a) for k in t["key_facts"] for a in k.split("|")]
            for raw in TYPED_ID.findall(t["user"]):
                tidied = tidy_id(raw)
                if tidied is None: continue
                if raw.upper() != tidied:                      # malformed -> confirm first (R6b)
                    if not CLAIM_TOOLS <= set(t["forbidden_tools"]):
                        e(f"malformed ID {raw!r}: claim tools must be forbidden until confirmed", i)
                    if norm(tidied) not in key_norm:
                        e(f"malformed ID {raw!r}: tidied {tidied} must be a key fact", i)
                elif tidied not in claims or claims[tidied]["member_id"] != mid:   # not theirs (R3)
                    if arg_id == tidied: e(f"{tidied} is not this member's but is expected from the tool", i)
                    if "can't find that claim" not in key_norm and not CLAIM_TOOLS <= set(t["forbidden_tools"]) \
                            and "no_leak" not in t["judge_checks"]:
                        e(f"{tidied} is not this member's: expect the not-found reply or a no_leak check", i)

            # 4. traceability
            texts = []
            for s in t["fact_sources"]:
                kind, _, ref = s.partition(":")
                if kind == "claim":
                    if ref not in claims: e(f"source {s} does not exist", i); continue
                    if claims[ref]["member_id"] != mid: e(f"source {s} is another member's claim", i)
                    texts.append(" ".join(claims[ref].values()))
                elif kind == "doc":
                    if ref not in docs: e(f"source {s} does not exist", i); continue
                    texts.append(docs[ref])
                elif kind == "spec":
                    texts.append(spec)
                elif kind == "id":
                    texts.append(tidy_id(ref) or "")
                else:
                    e(f"unknown source kind {s}", i)
            blob = norm(" ".join(texts))
            for k in t["key_facts"]:
                if not any(norm(a) in blob for a in k.split("|")):
                    e(f"key fact {k!r} not found in its sources {t['fact_sources']}", i)

            # 5. contradiction
            for a in t["absent_terms"]:
                if norm(a) in key_norm: e(f"{a!r} is both a key fact and an absent term", i)

            # 6. unanswerable terms
            for term in t["not_in_corpus"]:
                hits = [d for d, txt in docs.items() if norm(term) in norm(txt)]
                if hits: e(f"{term!r} is meant to be absent but appears in {hits}", i)

    counted = [c for c in golden["conversations"] if not c["stretch"]]
    print(f"{len(golden['conversations'])} conversations ({len(counted)} scored, "
          f"{len(golden['conversations']) - len(counted)} stretch), "
          f"{sum(len(c['turns']) for c in golden['conversations'])} turns, "
          f"{len(members)} members, {len(claims)} claims")
    for p in [GOLDEN, SPEC, STATUS, M5_DOCS / "10_contact_and_privacy.md"]:
        print(f"  {p.relative_to(ROOT)}  {fingerprint(p)}")
    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for msg in errors: print("  -", msg)
        return 1
    print("PASS: all checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
