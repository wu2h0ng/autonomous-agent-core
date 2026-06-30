"""ADR-0044 Coding-Agent Seam Prototype (resumed core research prototype, real tasks).

The seam on a REAL model + REAL coding tasks:
  proposer = Kimi LLM (writes the function);
  causal world model = INTERVENTIONAL VERIFICATION (run the tests, observe the real effect);
  governable disposer = confidence-gated escalation (verify pass -> commit; fail -> retry -> escalate).

Metric = human interventions per task. Reads KIMI_API_KEY from env; never persists it.
Run: KIMI_API_KEY=... PYTHONPATH=src python experiments/coding_agent_seam_g1.py
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error

BASE = os.environ.get("KIMI_BASE", "https://api.kimi.com/coding/v1")
MODEL = os.environ.get("KIMI_MODEL", "kimi-for-coding")

# (name, signature, spec, tests as (args_tuple, expected))
TASKS = [
    ("is_prime", "is_prime(n: int) -> bool",
     "Return True iff n is a prime number (n>=2). 0,1 and negatives are not prime.",
     [((2,), True), ((1,), False), ((0,), False), ((17,), True), ((18,), False), ((97,), True)]),
    ("fibonacci", "fibonacci(n: int) -> int",
     "Return the n-th Fibonacci number, 0-indexed: fibonacci(0)=0, fibonacci(1)=1.",
     [((0,), 0), ((1,), 1), ((2,), 1), ((7,), 13), ((10,), 55)]),
    ("reverse_words", "reverse_words(s: str) -> str",
     "Reverse the order of words in s (words separated by single spaces). 'a b c' -> 'c b a'.",
     [(("a b c",), "c b a"), (("hello world",), "world hello"), (("x",), "x")]),
    ("flatten", "flatten(lst: list) -> list",
     "Flatten ONE level of nesting: [[1,2],[3],[4,5]] -> [1,2,3,4,5]. Non-list elements pass through.",
     [(([[1, 2], [3], [4, 5]],), [1, 2, 3, 4, 5]), (([[1], [2, 3]],), [1, 2, 3])]),
    ("roman_to_int", "roman_to_int(s: str) -> int",
     "Convert a Roman numeral string to its integer value. 'IV'->4, 'IX'->9, 'LVIII'->58, 'MCMXCIV'->1994.",
     [(("IV",), 4), (("IX",), 9), (("LVIII",), 58), (("MCMXCIV",), 1994), (("III",), 3)]),
    ("is_balanced", "is_balanced(s: str) -> bool",
     "Return True iff the brackets in s are balanced and correctly nested, for ()[]{}. Ignore other chars.",
     [(("()",), True), (("()[]{}",), True), (("(]",), False), (("([)]",), False), (("{[]}",), True)]),
    # --- harder, edge-case-heavy (to stress the seam) ---
    ("my_atoi", "my_atoi(s: str) -> int",
     "LeetCode atoi: skip leading whitespace, optional +/- sign, read digits until a non-digit, "
     "ignore the rest; clamp to the signed 32-bit range [-2147483648, 2147483647]; return 0 if no digits.",
     [(("42",), 42), (("  -42",), -42), (("4193 with words",), 4193), (("words and 987",), 0),
      (("-91283472332",), -2147483648), (("2147483648",), 2147483647), (("+1",), 1), (("",), 0)]),
    ("is_valid_ipv4", "is_valid_ipv4(s: str) -> bool",
     "Strict IPv4: exactly 4 dot-separated octets, each an integer 0-255 with NO leading zeros "
     "(except the single digit '0'). No empty octets, no trailing dot, digits only.",
     [(("1.1.1.1",), True), (("255.255.255.255",), True), (("0.0.0.0",), True), (("256.1.1.1",), False),
      (("01.1.1.1",), False), (("1.1.1",), False), (("1.1.1.1.",), False), (("1.1.1.a",), False)]),
    ("eval_expr", "eval_expr(s: str) -> int",
     "Evaluate a string arithmetic expression with + - * / and integer operands (no parentheses). "
     "Respect precedence; division truncates toward zero. Whitespace may appear.",
     [(("3+2*2",), 7), ((" 3/2 ",), 1), (("3+5/2",), 5), (("14-3/2",), 13), (("1-1+1",), 1)]),
    ("merge_intervals", "merge_intervals(intervals: list) -> list",
     "Merge all overlapping (or touching) intervals; return sorted, non-overlapping intervals as lists.",
     [(([[1, 3], [2, 6], [8, 10], [15, 18]],), [[1, 6], [8, 10], [15, 18]]),
      (([[1, 4], [4, 5]],), [[1, 5]]), (([[1, 4], [0, 4]],), [[0, 4]]), (([[1, 4], [2, 3]],), [[1, 4]])]),
    ("spiral_order", "spiral_order(matrix: list) -> list",
     "Return all elements of the 2D matrix in clockwise spiral order starting from the top-left.",
     [(([[1, 2, 3], [4, 5, 6], [7, 8, 9]],), [1, 2, 3, 6, 9, 8, 7, 4, 5]),
      (([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]],), [1, 2, 3, 4, 8, 12, 11, 10, 9, 5, 6, 7]),
      (([[1]],), [1]), (([[1, 2], [3, 4]],), [1, 2, 4, 3])]),
]


def kimi_propose(name: str, sig: str, spec: str, feedback: str | None) -> str:
    key = os.environ["KIMI_API_KEY"]
    prompt = (
        f"Write a correct Python function.\nSignature: {sig}\nSpec: {spec}\n"
        "Return ONLY the function source (def ...), no prose, no markdown fences, no examples."
    )
    if feedback:
        prompt += f"\n\nYour previous attempt FAILED this check: {feedback}\nFix it; return only the function."
    body = json.dumps({"model": MODEL, "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    text = ""
    for attempt in range(4):
        try:
            req = urllib.request.Request(BASE + "/chat/completions", data=body,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            r = urllib.request.urlopen(req, timeout=150)
            text = json.loads(r.read())["choices"][0]["message"]["content"]
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                continue
            return ""  # graceful: a failed proposal -> verify fails -> retry/escalate
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < 3:
                continue
            return ""
    # strip markdown fences if present
    text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text.strip(), flags=re.MULTILINE)
    m = re.search(r"(def\s+\w+.*)", text, flags=re.DOTALL)
    return m.group(1) if m else text


def verify(code: str, name: str, tests) -> tuple[bool, str]:
    """Interventional probe: run the code on the tests, observe the real effect."""
    try:
        ns: dict = {}
        exec(code, ns)  # noqa: S102 - prototype sandbox over a fixed task set
        fn = ns.get(name)
        if fn is None:
            return False, f"function {name} not defined"
        for args, expected in tests:
            got = fn(*args)
            if got != expected:
                return False, f"{name}{args} returned {got!r}, expected {expected!r}"
        return True, "all tests pass"
    except Exception as e:  # noqa: BLE001
        return False, f"exception: {type(e).__name__}: {e}"


def run_seam() -> dict:
    interv = 0
    auto_ok = 0
    silent_fail = 0
    detail = []
    for name, sig, spec, tests in TASKS:
        code = kimi_propose(name, sig, spec, None)
        ok, msg = verify(code, name, tests)
        if ok:
            auto_ok += 1
            detail.append((name, "auto-pass (1 try)"))
            continue
        code2 = kimi_propose(name, sig, spec, msg)         # retry with the real failure
        ok2, msg2 = verify(code2, name, tests)
        if ok2:
            auto_ok += 1
            detail.append((name, "auto-pass (after verify+retry)"))
        else:
            interv += 1                                     # escalate to human
            detail.append((name, f"ESCALATED ({msg2[:40]})"))
    return {"interventions": interv, "auto_ok": auto_ok, "silent_fail": silent_fail, "detail": detail}


def run_no_verify() -> dict:
    """Surface baseline: commit the first guess without running the tests."""
    interv = 0
    auto_ok = 0
    silent_fail = 0
    detail = []
    for name, sig, spec, tests in TASKS:
        code = kimi_propose(name, sig, spec, None)
        ok, _ = verify(code, name, tests)                   # we check only to SCORE; the agent committed blind
        if ok:
            auto_ok += 1
            detail.append((name, "committed (happened to pass)"))
        else:
            silent_fail += 1
            detail.append((name, "SILENT BROKEN COMMIT"))
    return {"interventions": interv, "auto_ok": auto_ok, "silent_fail": silent_fail, "detail": detail}


def main() -> None:
    n = len(TASKS)
    print(f"ADR-0044 Coding-Agent Seam Prototype  model={MODEL}  tasks={n}")
    seam = run_seam()
    nover = run_no_verify()
    print("\n=== SEAM (proposer + interventional verify + governable escalation) ===")
    for t, d in seam["detail"]:
        print(f"   {t:>14}: {d}")
    print(f"  interventions/task = {seam['interventions']}/{n} = {seam['interventions']/n:.2f}")
    print(f"  autonomous success = {seam['auto_ok']}/{n};  silent broken commits = {seam['silent_fail']}/{n}")

    print("\n=== NO-VERIFY (surface: commit first guess, no test run) ===")
    for t, d in nover["detail"]:
        print(f"   {t:>14}: {d}")
    print(f"  silent broken commits = {nover['silent_fail']}/{n}  (the cost of no interventional grounding)")

    print("\n=== ALWAYS-ASK (no autonomy) ===")
    print(f"  interventions/task = {n}/{n} = 1.00  (the interaction ceiling)")

    print("\n=== READING ===")
    print(f"  SEAM: {seam['auto_ok']}/{n} done autonomously, {seam['interventions']}/{n} interventions, "
          f"{seam['silent_fail']} silent failures.")
    print(f"  vs ALWAYS-ASK 1.00 interventions/task; vs NO-VERIFY {nover['silent_fail']}/{n} silent broken commits.")
    print("  The seam does the work, verifies its own effects (no broken commits), and only asks when it genuinely can't.")


if __name__ == "__main__":
    main()
