#!/usr/bin/env python3
"""Scoring pipeline for report_rc titles (LLM scores prepared/applied here).

The LLM step itself runs inside an omp session (completion tool, model=smol,
-5..+5 integer per title); this script only extracts batches and applies
scored JSON, so the whole pipeline is reproducible:

  1. python scripts/score_research_titles.py extract --db DB --out batches.json
  2. (in session) score every batch -> scores.json  {title: int in -5..5}
  3. python scripts/score_research_titles.py apply --db DB --scores scores.json

Downsampling (extract): identical titles are deduped (same text => same
score) and each (ts_code, week) keeps at most 10 distinct titles.
Aggregation (apply): per (ts_code, week) over rows whose title was scored,
bull_ratio = (mean_score + 5) / 10 so the strategy wrapper recovers
score = 2 * bull_ratio - 1 = mean_score / 5. Rows with unscored titles
(dropped by the cap) are excluded from that week's aggregate.
research_sentiment is derived data: dropped and rebuilt on every apply;
report_rc is never modified.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

BATCH_SIZE = 50
CAP_PER_CODE_WEEK = 10


def _week_of(date_str: str) -> str:
    d = datetime.strptime(date_str[:8], "%Y%m%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y%m%d")


def _load_rows(db: str) -> List[Tuple[str, str, str]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT ts_code, report_date, report_title FROM report_rc "
            "ORDER BY report_date, ts_code"
        ).fetchall()
    finally:
        conn.close()


def cmd_extract(args: argparse.Namespace) -> int:
    seen: set = set()
    per_group: Dict[Tuple[str, str], int] = {}
    titles: List[str] = []
    for code, date, title in _load_rows(args.db):
        text = (title or "").strip()
        if not text or text in seen:
            continue
        key = (code, _week_of(date))
        if per_group.get(key, 0) >= CAP_PER_CODE_WEEK:
            continue
        per_group[key] = per_group.get(key, 0) + 1
        seen.add(text)
        titles.append(text)
    batches = [
        titles[i : i + BATCH_SIZE] for i in range(0, len(titles), BATCH_SIZE)
    ]
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"titles": titles, "batches": batches}, fh, ensure_ascii=False)
    print(f"rows scored-eligible: {len(titles)} titles, {len(batches)} batches")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    with open(args.scores, encoding="utf-8") as fh:
        scores = {k.strip(): int(v) for k, v in json.load(fh).items()}
    agg: Dict[Tuple[str, str], List[int]] = {}
    missing = 0
    for code, date, title in _load_rows(args.db):
        text = (title or "").strip()
        if text not in scores:
            missing += 1
            continue
        agg.setdefault((code, _week_of(date)), []).append(scores[text])
    rows = []
    for (code, week), vals in sorted(agg.items()):
        n = len(vals)
        mean = sum(vals) / n
        rows.append(
            (
                code,
                week,
                n,
                sum(1 for v in vals if v > 0),
                sum(1 for v in vals if v < 0),
                round((mean + 5) / 10, 4),
            )
        )
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("DROP TABLE IF EXISTS research_sentiment")
        conn.execute(
            "CREATE TABLE research_sentiment (ts_code TEXT, week TEXT, "
            "n_reports INT, n_bull INT, n_bear INT, bull_ratio REAL, "
            "PRIMARY KEY (ts_code, week))"
        )
        conn.executemany(
            "INSERT INTO research_sentiment VALUES (?,?,?,?,?,?)", rows
        )
        conn.commit()
    finally:
        conn.close()
    print(f"research_sentiment rebuilt: {len(rows)} rows, {missing} unscored rows skipped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ex = sub.add_parser("extract", help="emit deduped title batches as JSON")
    p_ex.add_argument("--db", required=True)
    p_ex.add_argument("--out", required=True)
    p_ex.set_defaults(fn=cmd_extract)
    p_ap = sub.add_parser("apply", help="aggregate scored JSON into research_sentiment")
    p_ap.add_argument("--db", required=True)
    p_ap.add_argument("--scores", required=True)
    p_ap.set_defaults(fn=cmd_apply)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
