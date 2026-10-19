"""Answer the DSO 429 hourly quiz with plain arithmetic (no LLM).

Reads questions.csv, writes answers/round-NNNN.json for every round that has
no answer file yet. Usage:
    python solver.py                 # answer new rounds from the live CSV
    python solver.py --check KEYS    # score against practice_keys.csv
"""
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

QUESTIONS_URL = "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/main/questions.csv"
KEYS_URL = "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/main/practice_keys.csv"
ANSWERS = Path(__file__).parent / "answers"
LETTERS = "ABCD"


def nums(text):
    return [float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text)]


def parse_date(text):
    return datetime.strptime(text.strip(), "%d %B %Y").date()


def compute(q):
    """Return the exact answer: a float, or a date for settlement questions."""
    t = q.lower()
    n = nums(q)
    if "settlement period" in t:
        signed = re.search(r"signed on (\d{1,2} \w+ \d{4})", q).group(1)
        days = int(re.search(r"(\d+)-day", q).group(1))
        return parse_date(signed) + timedelta(days=days)
    if "euros per us dollar" in t:
        return n[0] * n[1]
    if "dollars per euro" in t:
        return n[0] / n[1]
    if "units at" in t and "total revenue" in t:
        return n[0] * n[1]
    if "gross margin" in t:
        return (n[0] - n[1]) / n[0] * 100
    if "break even" in t:
        return n[0] / (n[1] - n[2])
    if "discounted by" in t:
        return n[0] * (1 - n[1] / 100)
    if "percentage change" in t:
        return (n[1] - n[0]) / n[0] * 100
    if "average order value" in t:
        return (n[0] * n[1] + n[2] * n[3]) / (n[0] + n[2])
    if "compounded" in t:
        return n[0] * (1 + n[1] / 100) ** n[2]
    if "probability" in t:
        counts = re.findall(r"(\d+) (\w+) tickets?", q)
        want = re.search(r"it is an? (\w+) ticket", q).group(1)
        total = sum(int(c) for c, _ in counts)
        return next(int(c) for c, k in counts if k == want) / total * 100
    if "in the ratio" in t:
        a, b = map(float, re.search(r"ratio (\d+):(\d+)", q).groups())
        share = a if ("first" in t.split("ratio")[1]) else b
        return n[0] * share / (a + b)
    if "next value" in t:
        seq = [float(x) for x in re.search(r"runs ([\d,\s.]+?)\.?\s*If", q).group(1).replace(",", " ").split()]
        diffs = {round(seq[i + 1] - seq[i], 6) for i in range(len(seq) - 1)}
        if len(diffs) == 1:
            return seq[-1] + diffs.pop()
        return seq[-1] * seq[-1] / seq[-2]  # geometric fallback
    raise ValueError("unknown template")


def pick(q, options):
    try:
        ans = compute(q)
    except Exception as e:  # unknown wording: log it, guess
        print(f"  !! could not solve ({e}): {q}", file=sys.stderr)
        return "A"
    if isinstance(ans, date):
        for letter, opt in zip(LETTERS, options):
            try:
                if parse_date(opt) == ans:
                    return letter
            except ValueError:
                pass
        print(f"  !! no date option matched: {q}", file=sys.stderr)
        return "A"
    vals = [nums(o)[0] if nums(o) else float("inf") for o in options]
    return LETTERS[min(range(4), key=lambda i: abs(vals[i] - ans))]


def load(url_or_path):
    if url_or_path.startswith("http"):
        req = urllib.request.Request(url_or_path, headers={"Cache-Control": "no-cache"})
        text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    else:
        text = Path(url_or_path).read_text()
    return list(csv.DictReader(io.StringIO(text)))


def solve_all(rows):
    rounds = {}
    for r in rows:
        opts = [r["option_a"], r["option_b"], r["option_c"], r["option_d"]]
        rounds.setdefault(int(r["round_id"]), {})[f"q{int(r['q_index'])}"] = pick(r["question_text"], opts)
    return rounds


def main():
    args = sys.argv[1:]
    src = QUESTIONS_URL
    if "--questions" in args:
        src = args[args.index("--questions") + 1]
    rounds = solve_all(load(src))
    if "--check" in args:
        keys = load(args[args.index("--check") + 1] if len(args) > args.index("--check") + 1 else KEYS_URL)
        right = sum(rounds[int(k["round_id"])][f"q{int(k['q_index'])}"] == k["answer"] for k in keys)
        print(f"{right}/{len(keys)} correct on practice keys")
        return
    ANSWERS.mkdir(exist_ok=True)
    for rid in sorted(rounds):
        path = ANSWERS / f"round-{rid:04d}.json"
        if path.exists():
            continue
        ans = rounds[rid]
        if len(ans) != 25:
            print(f"round {rid}: only {len(ans)} questions so far, skipping", file=sys.stderr)
            continue
        ordered = {f"q{i}": ans[f"q{i}"] for i in range(1, 26)}
        path.write_text(json.dumps({"round_id": rid, "answers": ordered}, indent=2) + "\n")
        print(f"wrote {path.name}")


if __name__ == "__main__":
    main()
