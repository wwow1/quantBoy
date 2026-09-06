#!/usr/bin/env python3
"""Research-factor pipeline for report_rc (structured + LLM title scores).

Components per (ts_code, week), each in [-1, 1]:
- title_score : mean of in-session LLM scores (-5..+5) / 5
- rating_chg  : mean ordinal rating change vs the same org's previous
  report (sell<reduce<neutral<overweight<buy = 1..5), diff / 2 clipped
- eps_rev     : mean EPS revision vs same (org, quarter) previous report,
  relative change * 2 clipped to +-1
composite = equal-weight mean of the components available that week
(zero-valued structured components count as "no event" and are skipped);
bull_ratio = (composite + 1) / 2 so the strategy wrapper recovers
score = 2 * bull_ratio - 1 = composite. n_reports = coverage (all rows),
n_bull/n_bear = positive/negative evidence counts (titles + events).

The LLM step itself runs inside an omp session (completion tool,
model=smol); this script only extracts batches and applies scored JSON:

  1. python scripts/score_research_titles.py extract --db DB --out batches.json
  2. (in session) score every batch -> scores.json  {title: int in -5..5}
  3. python scripts/score_research_titles.py apply --db DB --scores scores.json

Downsampling (extract): identical titles are deduped (same text => same
score) and each (ts_code, week) keeps at most 10 distinct titles.
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

RATING_ORD = {
    "卖出": 1, "Sell": 1,
    "减持": 2, "Underweight": 2,
    "中性": 3, "Neutral": 3, "持有": 3,
    "增持": 4, "Overweight": 4, "优于大市": 4, "跑赢行业": 4,
    "买入": 5, "Buy": 5, "推荐": 5, "强烈推荐": 5,
}


def _week_of(date_str: str) -> str:
    d = datetime.strptime(date_str[:8], "%Y%m%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y%m%d")


def _load_rows(db: str) -> List[Tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT ts_code, report_date, report_title, rating, eps, "
            "quarter, org_name FROM report_rc ORDER BY report_date, ts_code"
        ).fetchall()
    finally:
        conn.close()


def _structured(
    rows: List[Tuple],
) -> Dict[Tuple[str, str], Tuple[float, float, int, int, int]]:
    """(ts_code, week) -> (rating_chg mean, eps_rev mean, n_pos, n_neg, coverage)."""
    by_org: Dict[Tuple[str, str, str], List[Tuple]] = {}
    for code, date, _t, rating, eps, quarter, org in rows:
        by_org.setdefault((code, str(org or ""), str(quarter or "")), []).append(
            (date, rating, eps)
        )
    rating_events: Dict[Tuple[str, str], List[float]] = {}
    eps_events: Dict[Tuple[str, str], List[float]] = {}
    n_pos: Dict[Tuple[str, str], int] = {}
    n_neg: Dict[Tuple[str, str], int] = {}
    for (code, _org, _q), items in by_org.items():
        prev_r = None
        prev_e = None
        for date, rating, eps in sorted(items):
            week = _week_of(date)
            key = (code, week)
            r = RATING_ORD.get(str(rating or "").strip())
            if r is not None and prev_r is not None and r != prev_r:
                rating_events.setdefault(key, []).append((r - prev_r) / 2.0)
                if r > prev_r:
                    n_pos[key] = n_pos.get(key, 0) + 1
                else:
                    n_neg[key] = n_neg.get(key, 0) + 1
            if r is not None:
                prev_r = r
            e = float(eps) if eps is not None else None
            if e is not None and prev_e not in (None, 0.0):
                rel = max(-0.5, min(0.5, (e - prev_e) / abs(prev_e))) * 2.0
                eps_events.setdefault(key, []).append(rel)
                if e > prev_e:
                    n_pos[key] = n_pos.get(key, 0) + 1
                else:
                    n_neg[key] = n_neg.get(key, 0) + 1
            if e is not None:
                prev_e = e
    cover: Dict[Tuple[str, str], int] = {}
    for code, date, _t, _r, _e, _q, _o in rows:
        key = (code, _week_of(date))
        cover[key] = cover.get(key, 0) + 1
    out = {}
    for key in cover:
        rc = rating_events.get(key)
        er = eps_events.get(key)
        out[key] = (
            round(sum(rc) / len(rc), 4) if rc else 0.0,
            round(sum(er) / len(er), 4) if er else 0.0,
            n_pos.get(key, 0),
            n_neg.get(key, 0),
            cover[key],
        )
    return out


def cmd_extract(args: argparse.Namespace) -> int:
    seen: set = set()
    per_group: Dict[Tuple[str, str], int] = {}
    titles: List[str] = []
    for row in _load_rows(args.db):
        text = (row[2] or "").strip()
        if not text or text in seen:
            continue
        key = (row[0], _week_of(row[1]))
        if per_group.get(key, 0) >= CAP_PER_CODE_WEEK:
            continue
        per_group[key] = per_group.get(key, 0) + 1
        seen.add(text)
        titles.append(text)
    batches = [titles[i : i + BATCH_SIZE] for i in range(0, len(titles), BATCH_SIZE)]
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"titles": titles, "batches": batches}, fh, ensure_ascii=False)
    print(f"rows scored-eligible: {len(titles)} titles, {len(batches)} batches")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    with open(args.scores, encoding="utf-8") as fh:
        scores = {k.strip(): int(v) for k, v in json.load(fh).items()}
    rows = _load_rows(args.db)
    struct = _structured(rows)
    title_agg: Dict[Tuple[str, str], List[int]] = {}
    missing = 0
    for code, date, title, _r, _e, _q, _o in rows:
        text = (title or "").strip()
        if text not in scores:
            missing += 1
            continue
        title_agg.setdefault((code, _week_of(date)), []).append(scores[text])
    out_rows = []
    for key in sorted(struct):
        code, week = key
        rc, er, npos, nneg, cov = struct[key]
        ts = title_agg.get(key)
        comps = [c for c in (rc, er) if c != 0.0]
        if ts:
            comps.append(sum(ts) / len(ts) / 5.0)
        if not comps:
            continue
        composite = sum(comps) / len(comps)
        bull_ratio = round((composite + 1.0) / 2.0, 4)
        n_bull = sum(1 for v in (ts or []) if v > 0) + npos
        n_bear = sum(1 for v in (ts or []) if v < 0) + nneg
        out_rows.append((code, week, cov, n_bull, n_bear, bull_ratio))
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("DROP TABLE IF EXISTS research_sentiment")
        conn.execute(
            "CREATE TABLE research_sentiment (ts_code TEXT, week TEXT, "
            "n_reports INT, n_bull INT, n_bear INT, bull_ratio REAL, "
            "PRIMARY KEY (ts_code, week))"
        )
        conn.executemany(
            "INSERT INTO research_sentiment VALUES (?,?,?,?,?,?)", out_rows
        )
        conn.commit()
    finally:
        conn.close()
    print(
        f"research_sentiment rebuilt: {len(out_rows)} rows, "
        f"{missing} unscored title rows skipped"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ex = sub.add_parser("extract", help="emit deduped title batches as JSON")
    p_ex.add_argument("--db", required=True)
    p_ex.add_argument("--out", required=True)
    p_ex.set_defaults(fn=cmd_extract)
    p_ap = sub.add_parser("apply", help="aggregate scores into research_sentiment")
    p_ap.add_argument("--db", required=True)
    p_ap.add_argument("--scores", required=True)
    p_ap.set_defaults(fn=cmd_apply)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
