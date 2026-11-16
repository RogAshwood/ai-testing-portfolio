"""lints.py: free style lints for test cases. Every lint gives warnings only.

Lints (settings and word lists in harness/lint_rules.toml)
-----------------------------------------------------------
  generic_title       the title says nothing about the test ("Test 1", "Verify AC2")
  vague_steps         preconditions or steps leave the tester guessing ("navigate to", "valid data")
  vague_expected      an expected result (case-level or per step) cannot be checked ("as expected")
  repeated_expected   copy-paste expected results: the same wording on several steps of a case,
                      or the identical expected result on several cases of a story
  missing_test_data   no concrete value (number, date, quoted text) in preconditions or steps
                      (off by default: wrong 17 times in 23 on the Day 4 labels)
  placeholders        leftover template text (TBD, xxx, <value>)
  near_duplicate      wording nearly repeats an earlier case (TF-IDF), and by default
                      only when both cases also use the same test values
  boundary_hint       a number in an AC with no case at it, or none either side (two-value BVA by default;
                      three-value: none just below or just above)
                      (story-level, so case_id is ""); a period such as "12 months" gets an
                      "info" reminder instead, because its boundary is a date
  step_detail         low-level cases only (case_detail = "low-level"): too few steps, or a step that
                      does not say where or how; does nothing for high-level cases (the default)

How to read a lint warning: "worth a human look", not "this case is wrong".
How often each lint is right is measured on the Day 4 cases by measure_lints.py.

Change history:
  2026-11-12  v1  first version (M7 step 1).
  2026-11-12  v2  Roger's review: repeated_expected lint; step objects with per-step expected results;
                  missing_test_data off by default; SBERT dropped (text similarity cannot tell whether a
                  difference matters to the rule; duplicates stay with the judge).
  2026-11-12  v3  boundary_hint reads the kind of value from the words around each number (Roger's
                  review sheet): whole steps and nothing below 0 for counts and days; durations such as
                  "12 months" get a date-boundary message instead of 11 / 13.
  2026-11-13  v4  two-value BVA by default (bva setting); step_detail lint for low-level cases (case_detail);
                  clock times (02:00, 23:59) are not read as numbers; ages ("18 or over") get a birthday reminder.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from harness.contract import Finding, actions, all_expected, case_key, flat_case, input_text, step_expecteds

RULES_PATH = Path(__file__).resolve().parent / "lint_rules.toml"
LINT_NAMES = ("generic_title", "vague_steps", "vague_expected", "repeated_expected", "missing_test_data",
              "placeholders", "near_duplicate", "boundary_hint", "step_detail")

# --- finding test values in text -----------------------------------------------------
_MONTHS = (r"(?:january|february|march|april|may|june|july|august|september|october|november|december"
           r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)")
# Dates: 2026-03-10, 10/03/2026, "10 March 2027" and "29 February" (a day and month with no year),
# and clock times such as 02:00 or 23:59, so their digits are not read as limits.
_DATE = re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b"
                   rf"|\b\d{{1,2}} {_MONTHS}\b(?: \d{{4}}\b)?|\b\d{{1,2}}:\d{{2}}(?::\d{{2}})?\b", re.I)
# A number not glued to letters, so "AC2", "TC01" and reason codes are not values.
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.,])[€$£]?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![A-Za-z0-9_])")
# Quoted text. A single quote counts only when it is not an apostrophe ("member's" is not a quote).
_QUOTED = re.compile(r"\"([^\"]{2,})\"|“([^”]{2,})”|(?<![A-Za-z])'([^']{2,})'(?![A-Za-z])")


def numbers_in(text: str) -> set[float]:
    """Every number in the text (dates removed first), as a float: '1,000.00' -> 1000.0."""
    text = _DATE.sub(" ", text)
    return {float(m.group(1).replace(",", "")) for m in _NUMBER.finditer(text)}


def values_in(text: str) -> set[str]:
    """Every concrete test value in the text: numbers, dates and quoted text, normalised."""
    dates = {d.lower() for d in _DATE.findall(text)}
    nums = {f"{n:g}" for n in numbers_in(text)}
    quoted = {next(g for g in m.groups() if g).strip().lower() for m in _QUOTED.finditer(text)}
    return dates | nums | quoted


def _phrase_regex(phrases: list[str]) -> re.Pattern:
    """One case-insensitive regex that matches any phrase as whole words."""
    alts = "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z])(?:{alts})(?![A-Za-z])", re.I)


# --- settings ------------------------------------------------------------------------
def load_rules(path: Path = RULES_PATH, only: list[str] | None = None) -> dict:
    """Read the lint settings. `only` (from --lints) switches on just those lints."""
    with open(path, "rb") as f:
        rules = tomllib.load(f)
    unknown = [n for n in (only or []) if n not in LINT_NAMES]
    if unknown:
        raise ValueError(f"unknown lint(s) {unknown}; choose from {', '.join(LINT_NAMES)}")
    if only is not None:
        for name in LINT_NAMES:
            rules.setdefault(name, {})["enabled"] = name in only
    return rules


# --- the lints (each takes one story and its cases, returns findings) ----------------
def lint_generic_title(story: dict, cases: list[dict], cfg: dict) -> list[Finding]:
    """Warn when a title is too short or matches a 'says nothing' pattern."""
    pats = [re.compile(p, re.I) for p in cfg.get("patterns", [])]
    out = []
    for n, c in enumerate(cases, start=1):
        title = (c.get("title") or "").strip() if isinstance(c, dict) else ""
        if not title:
            continue                                     # empty titles fail in checks.py
        if any(p.match(title) for p in pats):
            out.append(Finding(story["story_id"], case_key(c, n), "generic_title", "warn",
                               f"the title '{title}' does not say what is being tested"))
        elif len(title.split()) < cfg.get("min_words", 3):
            out.append(Finding(story["story_id"], case_key(c, n), "generic_title", "warn",
                               f"the title '{title}' is very short; a reader may not tell what it tests"))
    return out


def _phrase_lint(story, cases, cfg, name, get_text, what) -> list[Finding]:
    """Shared logic for the two word-list lints: report the phrases found in the text get_text(case) returns."""
    rx = _phrase_regex(cfg.get("phrases", []))
    out = []
    for n, c in enumerate(cases, start=1):
        if not isinstance(c, dict):
            continue
        found = sorted({m.group(0).lower() for m in rx.finditer(" ".join(get_text(c)))})
        if found:
            out.append(Finding(story["story_id"], case_key(c, n), name, "warn",
                               f"{what} uses vague wording: {', '.join(repr(f) for f in found)}"))
    return out


def _preconditions(case: dict) -> list[str]:
    """The case's preconditions as a list of text (empty if missing)."""
    pre = case.get("preconditions")
    return [p for p in pre if isinstance(p, str)] if isinstance(pre, list) else []


def _set_up_and_actions(case: dict) -> list[str]:
    """The text a tester follows to run the case: its preconditions and step actions."""
    return _preconditions(case) + actions(case)


def lint_vague_steps(story, cases, cfg) -> list[Finding]:
    """Warn when preconditions or step actions contain a phrase from the vague-steps list."""
    return _phrase_lint(story, cases, cfg, "vague_steps", _set_up_and_actions, "a step or precondition")


def lint_vague_expected(story, cases, cfg) -> list[Finding]:
    """Warn when any expected result (case-level or per step) contains a phrase from the vague-expected list."""
    return _phrase_lint(story, cases, cfg, "vague_expected", all_expected, "an expected result")


def lint_missing_test_data(story, cases, cfg) -> list[Finding]:
    """Warn when preconditions and step actions contain no number, date or quoted value."""
    out = []
    for n, c in enumerate(cases, start=1):
        if not isinstance(c, dict):
            continue
        if not values_in(" ".join(_preconditions(c) + actions(c))):
            out.append(Finding(story["story_id"], case_key(c, n), "missing_test_data", "warn",
                               "no concrete test value (number, date or quoted text) in the preconditions or steps"))
    return out


def lint_placeholders(story, cases, cfg) -> list[Finding]:
    """Warn when any text field holds leftover template text such as TBD or <value>."""
    pats = [re.compile(p, re.I) for p in cfg.get("patterns", [])]
    out = []
    for n, c in enumerate(cases, start=1):
        if not isinstance(c, dict):
            continue
        text = input_text(c) + " " + " ".join(all_expected(c))
        found = sorted({m.group(0) for p in pats for m in p.finditer(text)})
        if found:
            out.append(Finding(story["story_id"], case_key(c, n), "placeholders", "warn",
                               f"placeholder text left in the case: {', '.join(repr(f) for f in found)}"))
    return out


def _norm(text: str) -> str:
    """Lower-case, punctuation and extra spaces removed, for comparing expected results word for word."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def lint_repeated_expected(story, cases, cfg) -> list[Finding]:
    """Two checks on copy-paste expected results:
    - within a case: the same expected wording on `min_steps` or more steps;
    - across the story (only if across_cases is true): the identical case-level expected result
      on `min_cases` or more cases, reported once, on the first case, listing the others."""
    out = []
    for n, c in enumerate(cases, start=1):
        if not isinstance(c, dict):
            continue
        counts: dict[str, int] = {}
        for e in step_expecteds(c):
            counts[_norm(e)] = counts.get(_norm(e), 0) + 1
        repeated = [e for e, k in counts.items() if e and k >= cfg.get("min_steps", 2)]
        if repeated:
            out.append(Finding(story["story_id"], case_key(c, n), "repeated_expected", "warn",
                               f"the same expected result is repeated on several steps: '{repeated[0]}'"))
    if not cfg.get("across_cases", False):
        return out
    groups: dict[str, list[str]] = {}
    for n, c in enumerate(cases, start=1):
        if isinstance(c, dict) and isinstance(c.get("expected_result"), str) and c["expected_result"].strip():
            groups.setdefault(_norm(c["expected_result"]), []).append(case_key(c, n))
    for ids in groups.values():
        if len(ids) >= cfg.get("min_cases", 3):
            out.append(Finding(story["story_id"], ids[0], "repeated_expected", "warn",
                               f"{len(ids)} cases have word-for-word the same expected result: {', '.join(ids)}"))
    return out


def similar_pairs(cases: list[dict], threshold: float, method: str = "tfidf") -> list[tuple[int, int, float]]:
    """Compare every case with every other case in the story by wording, and return
    (earlier index, later index, similarity 0-1) for each pair at or above the threshold.
    TF-IDF uses the same text and settings as bench/score.py so results line up with Day 4."""
    if method != "tfidf":
        raise ValueError(f"near_duplicate method {method!r} is not supported (only 'tfidf'; SBERT was dropped, 12 Nov)")
    from bench.score import case_text
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    good = [i for i, c in enumerate(cases) if isinstance(c, dict)]      # skip broken cases
    if len(good) < 2:
        return []
    # One text per case (title, preconditions, steps, expected results), turned into word-weight
    # vectors; cosine similarity then scores each pair from 0 (no words shared) to 1 (identical).
    texts = [case_text(flat_case(cases[i])) for i in good]
    sims = cosine_similarity(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit_transform(texts))
    return [(good[a], good[b], round(float(sims[a, b]), 3))
            for a in range(len(good)) for b in range(a + 1, len(good)) if sims[a, b] >= threshold]


def lint_near_duplicate(story, cases, cfg) -> list[Finding]:
    """Warn on the later case of each near-identical pair. By default the pair must also use the
    same test values, so cases on different sides of a limit (1,000 vs 1,000.01) are not flagged."""
    out, flagged = [], set()          # flagged: later cases already warned about, so each is reported once
    for a, b, sim in similar_pairs(cases, cfg.get("threshold", 0.85), cfg.get("method", "tfidf")):
        if b in flagged:
            continue
        va, vb = values_in(input_text(cases[a])), values_in(input_text(cases[b]))
        same = va == vb
        if cfg.get("require_same_values", True):
            if not same:
                continue
            if not va and not cfg.get("flag_when_no_values", False):
                continue        # neither case has a value, so the values rule cannot tell them apart
        flagged.add(b)
        note = "and the same test values" if same and va else ("(neither has test values)" if same
                                                              else "(test values differ)")
        out.append(Finding(story["story_id"], case_key(cases[b], b + 1), "near_duplicate", "warn",
                           f"nearly repeats {case_key(cases[a], a + 1)} (similarity {sim:.2f}) {note}"))
    return out


def _fmt(x: float) -> str:
    """Show a number the way people write it: 1000 -> '1,000', 1000.01 -> '1,000.01'."""
    return f"{x:,.2f}" if x != int(x) else f"{int(x):,}"


def _blank(match: re.Match) -> str:
    """Spaces of the same length as the matched text, so later positions in the text do not move."""
    return " " * len(match.group(0))


_AGE_WORDS = re.compile(r"\b(age|aged|birth|birthday|years? old|older|younger)\b", re.I)


def numbers_with_units(text: str, cfg: dict, context: str = "") -> list[tuple[float, str, str]]:
    """Every number in an AC with what kind of value it is, read from the words around it:
    (number, kind, unit word). Kinds:
      count     a whole number of things ("8 visits", "2 procedures"): step 1, never below 0
      day       a day number or number of days ("day 182", "30 days"): step 1, never below 0
      duration  a period in months, weeks or years ("12 months"): the real boundary is a date
      age       "18 or over", "65 years old": the real boundary is a birthday (a date)
      amount    anything else, such as money ("1,000", "€60"): steps from `steps` (1 or 0.01)"""
    clean = _DATE.sub(_blank, text)                                # blank out dates, keep positions
    counts = {u.lower() for u in cfg.get("count_units", [])}
    days = {u.lower() for u in cfg.get("day_units", ["day", "days"])}
    durations = {u.lower() for u in cfg.get("duration_units", [])}
    out = []
    for m in _NUMBER.finditer(clean):
        value = float(m.group(1).replace(",", ""))
        prev = re.search(r"([A-Za-z]+)\s+$", clean[:m.start()])          # a word straight before ("day 182")
        before = prev.group(1).lower() if prev else ""
        # The unit is the word straight after the number ("8 visits"); "60, consultant visit"
        # or "50 per session" are amounts, because the next word is not a unit.
        after = re.findall(r"[A-Za-z]+", clean[m.end():m.end() + 30])[:1]
        nxt = after[0].lower() if after and re.match(r"\s*[A-Za-z]", clean[m.end():]) else ""
        age_after = re.match(r"\s+(or over|or older|or under|or younger|years? old|years? of age)\b", clean[m.end():], re.I)
        # "under 18" / "over 65": an age only when the story is about age (date of birth, aged, ...)
        age_before = (re.search(r"\b(under|over|younger than|older than|aged)\s+$", clean[:m.start()], re.I)
                      and value <= 130 and _AGE_WORDS.search(context or text))
        if age_after or age_before:
            kind, unit = "age", "years of age"            # "18 or over": the boundary is a birthday (a date)
        elif nxt in durations:
            kind, unit = "duration", nxt
        elif nxt in counts:
            kind, unit = "count", nxt
        elif nxt in days or before in days:
            kind, unit = "day", nxt if nxt in days else "day"
        else:
            kind, unit = "amount", ""
        out.append((value, kind, unit))
    return out


def _show(x: float, kind: str, unit: str) -> str:
    """A value as a reader would write it: 'day 181', '9 visits', '1,000.01'."""
    if kind == "day" and unit in ("day",):
        return f"day {_fmt(x)}"
    if kind in ("count", "day"):
        word = unit[:-1] if x == 1 and unit.endswith("s") else unit       # "1 procedure", not "1 procedures"
        return f"{_fmt(x)} {word}".strip()
    return _fmt(x)


def lint_boundary_hint(story, cases, cfg) -> list[Finding]:
    """For each number in each AC, warn if no case tests the boundary. Two-value (default): no case
    uses the number itself, or none uses a neighbour on either side. Three-value: also needs
    the neighbour on each side.
    The kind of value decides what "just below / just above" means (see numbers_with_units):
    whole steps for counts and days (and nothing below 0), 1 or 0.01 for amounts. For a duration
    such as "12 months" the boundary is a date this lint cannot see, so it says what to check instead."""
    # Every number used anywhere in the story's case inputs (rounded to cents so 1000.0 == 1000.00).
    used = set().union(*(numbers_in(input_text(c)) for c in cases if isinstance(c, dict))) if cases else set()
    used = {round(u, 2) for u in used}
    out = []
    for ac in story["acceptance_criteria"]:
        seen = set()
        context = " ".join(a["text"] for a in story["acceptance_criteria"])
        for n, kind, unit in numbers_with_units(ac["text"], cfg, context):   # each number in the AC is a possible limit
            if (n, kind) in seen:
                continue
            seen.add((n, kind))
            if kind in ("duration", "age"):
                # "info", not "warn": the lint cannot see whether such cases exist, so it only reminds
                what = (f"an age of {_fmt(n)}: its boundary is a date (the {_fmt(n)}th birthday)" if kind == "age"
                        else f"a period of {_fmt(n)} {unit}: its boundary is a date")
                end = "the birthday" if kind == "age" else "the date the period ends"
                out.append(Finding(story["story_id"], "", "boundary_hint", "info",
                                   f"{ac['ac_id']} mentions {what}, which this lint cannot check. Look for cases one "
                                   f"day before, on, and one day after {end}"))
                continue
            steps = [1] if kind in ("count", "day") else cfg.get("steps", [1, 0.01])
            missing = []                            # which of: on it / just below / just above is untested
            if round(n, 2) not in used:
                missing.append(f"the value itself ({_show(n, kind, unit)})")
            below = [n - s for s in steps if kind == "amount" or n - s >= 0]   # no negative counts or days
            above = [n + s for s in steps]
            has_below = any(round(v, 2) in used for v in below)
            has_above = any(round(v, 2) in used for v in above)
            if cfg.get("bva", "two-value") == "two-value":
                # Two-value: the limit plus the nearest value on the other side. Code cannot tell from the
                # wording which side is "other" ("more than" vs "before"), so a neighbour on either side counts.
                if not has_below and not has_above:
                    missing.append("a value just either side ("
                                   + " or ".join(_show(v, kind, unit) for v in below + above) + ")")
            else:
                # Three-value: the limit and the nearest value on each side.
                if below and not has_below:
                    missing.append("just below (" + " or ".join(_show(v, kind, unit) for v in below) + ")")
                if not has_above:
                    missing.append("just above (" + " or ".join(_show(v, kind, unit) for v in above) + ")")
            if missing:
                out.append(Finding(story["story_id"], "", "boundary_hint", "warn",
                                   f"{ac['ac_id']} mentions {_show(n, kind, unit)} but no case uses "
                                   + "; ".join(missing)))
    return out


def lint_step_detail(story, cases, cfg) -> list[Finding]:
    """Low-level test cases only (case_detail level = "low-level"): warn when a case has fewer than
    min_steps steps, or a step names an action without saying where or how (no screen, field,
    button, endpoint or channel word from `place_words`). High-level cases ("Submit the claim for
    assessment") are fine by design, so the lint does nothing then."""
    if cfg.get("level", "high-level") != "low-level":
        return []
    rx = _phrase_regex(cfg.get("place_words", []))
    out = []
    for n, c in enumerate(cases, start=1):
        if not isinstance(c, dict):
            continue
        steps = actions(c)
        if len(steps) < cfg.get("min_steps", 2):
            out.append(Finding(story["story_id"], case_key(c, n), "step_detail", "warn",
                               f"only {len(steps)} step{'s' if len(steps) != 1 else ''}; a low-level case "
                               f"usually needs at least {cfg.get('min_steps', 2)}"))
        vague = [i for i, st in enumerate(steps, start=1) if not rx.search(st)]
        if vague:
            out.append(Finding(story["story_id"], case_key(c, n), "step_detail", "warn",
                               f"step {', '.join(map(str, vague))} does not say where or how (no screen, field, "
                               "button, endpoint or channel)"))
    return out


LINTS = {
    "generic_title": lint_generic_title,
    "vague_steps": lint_vague_steps,
    "vague_expected": lint_vague_expected,
    "repeated_expected": lint_repeated_expected,
    "missing_test_data": lint_missing_test_data,
    "placeholders": lint_placeholders,
    "near_duplicate": lint_near_duplicate,
    "boundary_hint": lint_boundary_hint,
    "step_detail": lint_step_detail,
}


def run_lints(stories: dict[str, dict], groups: dict[str, list], rules: dict) -> list[Finding]:
    """Run every enabled lint over every story that has both a story and cases."""
    out: list[Finding] = []
    for sid, story in stories.items():
        cases = groups.get(sid)
        if not cases:
            continue
        for name, fn in LINTS.items():
            cfg = dict(rules.get(name, {}))
            if name == "step_detail":                       # the case_detail level lives in its own section
                cfg["level"] = rules.get("case_detail", {}).get("level", "high-level")
            if cfg.get("enabled", True):
                out.extend(fn(story, cases, cfg))
    return out
