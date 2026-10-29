"""golden.py: load the Day 4 golden set and build what the generator is allowed to see.

The leakage rule from the plan is enforced here, in code, not by convention:
`story_card()` uses only the fields in GENERATOR_FIELDS. The expected ideas,
basis references and open questions never reach the generator prompt.

Fingerprints are SHA-256 of the text with Windows line endings (CRLF)
normalised to LF, shortened to 12 characters, so the same content gives the same
fingerprint on Windows, in this container and on a GitHub Actions runner.

Three levels:
- golden set   the whole file. Any change at all.
- story card   per story: exactly what the generator saw. If it changes, that
               story's generated cases are stale and must be regenerated.
- story ideas  per story: the expected ideas the judge marks against. If they
               change, that story must be re-scored, but not regenerated.
A change to one story therefore invalidates that story only, not the other nine.

Change history:
  2026-10-23  v1  first version (Day 4).
  2026-10-23  v2  per-story fingerprints (card and ideas).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "datasets" / "testgen_golden.json"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# The only story fields the generator may see.
GENERATOR_FIELDS = ("story_id", "title", "as_a", "i_want", "so_that", "acceptance_criteria")


def fingerprint_text(text: str) -> str:
    """First 12 characters of the SHA-256 of `text`, line endings normalised."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:12]


def fingerprint(path: Path) -> str:
    return fingerprint_text(path.read_text(encoding="utf-8"))


def load_golden(path: Path = GOLDEN_PATH) -> dict:
    """Return the golden set, with its fingerprint added under '_fingerprint'."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_fingerprint"] = fingerprint(path)
    return data


def story_card(story: dict) -> str:
    """The text the generator receives for one story: ID, title, user story, ACs."""
    s = {k: story[k] for k in GENERATOR_FIELDS}
    acs = "\n".join(f"{a['ac_id']}: {a['text']}" for a in s["acceptance_criteria"])
    return (f"Story ID: {s['story_id']}\n"
            f"Title: {s['title']}\n"
            f"User story: As a {s['as_a']}, I want {s['i_want']}, so that {s['so_that']}.\n\n"
            f"Acceptance criteria:\n{acs}")


def story_fingerprints(story: dict) -> dict:
    """Per-story fingerprints: the card the generator sees, and the expected ideas."""
    ideas = json.dumps(story.get("expected_ideas", []), sort_keys=True,
                       ensure_ascii=False, separators=(",", ":"))
    return {"card": fingerprint_text(story_card(story)), "ideas": fingerprint_text(ideas)}


def load_named_prompt(name: str) -> tuple[str, str]:
    """Return (text, fingerprint) for bench/prompts/<name>.txt, e.g. 'judge_cases_v1'."""
    path = PROMPTS_DIR / f"{name}.txt"
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    return text, fingerprint_text(text)


def load_prompt(version: str) -> tuple[str, str]:
    """Return (prompt text, prompt fingerprint) for the generator, e.g. version='v1'."""
    return load_named_prompt(f"testgen_{version}")


if __name__ == "__main__":
    # Offline check: print the golden set version, fingerprints and one story card.
    g = load_golden()
    print(f"golden set v{g['version']}  fingerprint {g['_fingerprint']}  "
          f"{len(g['stories'])} stories")
    for v in ("v1", "v2"):
        print(f"prompt {v}  fingerprint {load_prompt(v)[1]}")
    print(f"\n{'story':<6} {'card':<13} ideas")
    for s in g["stories"]:
        fp = story_fingerprints(s)
        print(f"{s['story_id']:<6} {fp['card']:<13} {fp['ideas']}")
    card = story_card(g["stories"][4])
    leaked = [i["idea_id"] for s in g["stories"] for i in s["expected_ideas"] if i["idea"] in card]
    print(f"\n{card}\n\nleak check: {'FAIL ' + str(leaked) if leaked else 'no expected ideas in the card'}")
