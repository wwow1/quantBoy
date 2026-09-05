#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily backtest report: run strategies, generate HTML with equity curves + trades.

Configuration: scripts/daily_report.yaml

Usage:
    cd /root/services/quantBoy
    TUSHARE_TOKEN=$(cat /root/.tushare_token) \
    PYTHONPATH=strategy MPLCONFIGDIR=/tmp/matplotlib \
    .venv/bin/python scripts/daily_report.py
"""

from __future__ import annotations

import json
import math
import os
import pickle
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# Ensure strategy package is importable
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "strategy"))

VENV_PYTHON = str(PROJECT / ".venv" / "bin" / "python")
BUNDLE = str(PROJECT / "data" / "rqalpha_bundle" / "bundle")
OUTPUT_DIR = PROJECT / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = PROJECT / "scripts" / "daily_report.yaml"


def load_config() -> dict:
    """Load YAML config, with defaults."""
    defaults = {
        "start": "20260101",
        "end": "auto",
        "universe": [
            {"code": "510300", "name": "沪深300ETF"},
            {"code": "510500", "name": "中证500ETF"},
            {"code": "159915", "name": "创业板ETF"},
            {"code": "510050", "name": "上证50ETF"},
            {"code": "588000", "name": "科创50ETF"},
        ],
        "cash": 100000,
        "benchmark": "000300.XSHG",
        "slippage": "0.001",
    }
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        defaults.update(loaded)
    return defaults

CONFIG = load_config()

# Optional: fetch HS300 constituents from Tushare at runtime
def _fetch_hs300_stocks() -> list[dict]:
    """Fetch CSI 300 index weight from Tushare, return list of {code, name}."""
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        try:
            token = Path("/root/.tushare_token").read_text().strip()
        except Exception:
            pass
    if not token:
        print("Warning: no TUSHARE_TOKEN, skipping HS300 constituents.")
        return []

    import urllib.request
    import json as _json

    api_url = "http://api.tushare.pro"
    body = _json.dumps({
        "api_name": "index_weight",
        "token": token,
        "params": {"index_code": "000300.SH"},
        "fields": "con_code,trade_date",
    }).encode()
    try:
        req = urllib.request.Request(api_url, data=body,
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=30)
        data = _json.loads(resp.read())
        items = data.get("data", {}).get("items", [])
        if not items:
            print("Warning: HS300 index_weight returned no items.")
            return []
        # Find the latest trade_date and keep only that snapshot's codes
        dates = sorted(set(row[1] for row in items), reverse=True)
        latest_date = dates[0]
        latest_codes = set()
        for row in items:
            if row[1] == latest_date:
                latest_codes.add(row[0])  # e.g. "600519.SH"
        # Convert Tushare ts_code -> plain code (strip exchange suffix)
        result = []
        for ts_code in sorted(latest_codes):
            code = ts_code.split(".")[0]
            result.append({"code": code, "name": code})  # name resolved later from bundle
        print(f"  HS300: {len(result)} constituents (snapshot {latest_date})")
        return result
    except Exception as e:
        print(f"Warning: failed to fetch HS300 constituents: {e}")
        return []


def _is_tradable_stock(code: str) -> bool:
    """Exclude ChiNext (30x) / STAR (68x) stocks: account lacks permission.

    ETFs (51x/56x/58x/15x/16x) are unaffected -- exchange-traded funds do
    not require ChiNext/STAR trading permission.
    """
    if code.startswith(("51", "56", "58", "15", "16")):
        return True  # ETF / LOF
    return not code.startswith(("30", "68"))


# Build universe: config items + optional HS300 constituents
_base_universe = CONFIG.get("universe", [])
if CONFIG.get("hs300", False):
    _hs300 = _fetch_hs300_stocks()
    _existing_codes = {item["code"] for item in _base_universe}
    for s in _hs300:
        if s["code"] not in _existing_codes:
            _base_universe.append(s)
_excluded = [i["code"] for i in _base_universe if not _is_tradable_stock(i["code"])]
if _excluded:
    print(f"Universe: excluding {len(_excluded)} ChiNext/STAR stocks (no trading permission)")
UNIVERSE = [i for i in _base_universe if _is_tradable_stock(i["code"])]
CODES = ",".join(item["code"] for item in UNIVERSE)

# Resolve stock names from bundle instruments.pk for codes without display names
def _resolve_names_from_bundle():
    """Fill in display names from bundle instruments.pk for HS300 stocks."""
    try:
        import pickle
        ins_path = BUNDLE + "/instruments.pk"
        with open(ins_path, "rb") as f:
            instruments = pickle.load(f)
        # Build order_book_id -> symbol map
        name_map = {}
        for ins in instruments:
            obid = str(ins.get("order_book_id", ""))
            symbol = str(ins.get("symbol", ""))
            if obid and symbol:
                name_map[obid] = symbol
        # Fill in names for universe items that still use code as name
        for item in UNIVERSE:
            if item["name"] == item["code"]:
                code = item["code"]
                suffix = ".XSHG" if code.startswith(("5", "6")) else ".XSHE"
                obid = code + suffix
                if obid in name_map:
                    item["name"] = name_map[obid]
    except Exception as e:
        print(f"Warning: could not resolve names from bundle: {e}")

_resolve_names_from_bundle()

# RQAlpha order_book_id -> display name
CODE_NAMES = {}
for item in UNIVERSE:
    code = item["code"]
    suffix = ".XSHG" if code.startswith(("5", "6")) else ".XSHE"
    CODE_NAMES[code + suffix] = item["name"]
    CODE_NAMES[code] = item["name"]

CASH = CONFIG.get("cash", 100000)
BENCHMARK = CONFIG.get("benchmark", "000300.XSHG")
SLIPPAGE = str(CONFIG.get("slippage", "0.001"))
_etf_count = len([i for i in UNIVERSE if i["code"].startswith(("5", "1"))])
_stock_count = len(UNIVERSE) - _etf_count
print(f"Universe: {len(UNIVERSE)} instruments ({_etf_count} ETFs + {_stock_count} stocks)")

STRATEGIES = [
    {
        "name": "equal_weight",
        "label": "等权重",
        "env": {"QUANTBOY_RQ_STRATEGY": "equal_weight", "QUANTBOY_RQ_REBALANCE": "daily"},
    },
    {
        "name": "momentum",
        "label": "动量轮动",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "momentum",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "1",
        },
    },
    {
        "name": "dual_ma",
        "label": "双均线",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "dual_ma",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_SHORT_WINDOW": "20",
            "QUANTBOY_RQ_LONG_WINDOW": "120",
        },
    },
    {
        "name": "risk_parity",
        "label": "风险平价",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "risk_parity",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
        },
    },
    {
        "name": "stateful_accelerating_momentum",
        "label": "加速动量",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "stateful_accelerating_momentum",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_SHORT_LOOKBACK": "20",
            "QUANTBOY_RQ_LONG_LOOKBACK": "220",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "30",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "1",
            "QUANTBOY_RQ_SHORT_WEIGHT": "5.0",
            "QUANTBOY_RQ_TRAILING_DRAWDOWN": "0.08",
            "QUANTBOY_RQ_MA_EXIT_WINDOW": "999",
            "QUANTBOY_RQ_COOLDOWN_WEEKS": "2",
            "QUANTBOY_RQ_ALLOW_SWITCH": "1",
        },
    },
    {
        "name": "low_volatility",
        "label": "低波动优选",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "low_volatility",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_LOW_VOLATILITY_TOP_K": "3",
        },
    },
    {
        "name": "trend_timing",
        "label": "趋势择时",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "trend_timing",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_TREND_WINDOW": "200",
        },
    },
    {
        "name": "mean_reversion",
        "label": "均值回归",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "mean_reversion",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_MEAN_REVERSION_LOOKBACK": "20",
            "QUANTBOY_RQ_MEAN_REVERSION_TOP_K": "1",
            "QUANTBOY_RQ_TREND_WINDOW": "120",
        },
    },
    {
        "name": "volatility_target",
        "label": "波动率目标",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "volatility_target",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_VOLATILITY_LOOKBACK": "60",
            "QUANTBOY_RQ_TARGET_VOLATILITY": "0.10",
            "QUANTBOY_RQ_MAX_LEVERAGE": "1.0",
        },
    },
    {
        "name": "dual_momentum",
        "label": "双重动量",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "dual_momentum",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_MOMENTUM_LOOKBACK": "120",
            "QUANTBOY_RQ_MOMENTUM_TOP_K": "3",
            "QUANTBOY_RQ_MIN_RETURN": "0",
        },
    },
    {
        "name": "drawdown_control",
        "label": "回撤控制",
        "env": {
            "QUANTBOY_RQ_STRATEGY": "drawdown_control",
            "QUANTBOY_RQ_REBALANCE": "daily",
            "QUANTBOY_RQ_DRAWDOWN_LOOKBACK": "120",
            "QUANTBOY_RQ_MAX_DRAWDOWN": "0.08",
        },
    },
]

def get_bundle_date_range() -> tuple[str, str]:
    """Get data range for our backtest universe from bundle.

    Checks both funds.h5 (ETFs) and stocks.h5 (stocks) for our universe.
    Returns (earliest_first, latest_last).
    """
    try:
        import h5py

        firsts, lasts = [], []
        for h5_name in ["funds.h5", "stocks.h5"]:
            path = BUNDLE + "/" + h5_name
            try:
                f = h5py.File(path, "r")
            except Exception:
                continue
            for item in UNIVERSE:
                code = item["code"]
                suffix = ".XSHG" if code.startswith(("5", "6")) else ".XSHE"
                key = code + suffix
                if key in f:
                    data = f[key][:]
                    if len(data) > 0 and "datetime" in data.dtype.names:
                        firsts.append(str(data["datetime"][0])[:8])
                        lasts.append(str(data["datetime"][-1])[:8])
            f.close()
        if firsts and lasts:
            return min(firsts), max(lasts)
    except Exception as e:
        print(f"Warning: could not read bundle data range: {e}")
    return "20250101", "20260529"


def compute_start_end() -> tuple[str, str]:
    """Compute backtest start/end from config."""
    cfg_start = str(CONFIG.get("start", "20260101"))
    cfg_end = str(CONFIG.get("end", "auto"))
    _, bundle_last = get_bundle_date_range()
    end = bundle_last if cfg_end == "auto" else cfg_end
    return cfg_start, end


def run_backtest(strategy: dict, start: str, end: str) -> dict | None:
    """Run a single RQAlpha backtest, return result dict."""
    pkl_path = OUTPUT_DIR / f"daily_{strategy['name']}.pkl"
    env = os.environ.copy()
    env.update(strategy["env"])
    env["QUANTBOY_RQ_CODES"] = CODES
    env["QUANTBOY_RQ_USE_PRE_START_HISTORY"] = "1"
    env["QUANTBOY_RQ_HISTORY_BARS"] = "260"
    env["PYTHONPATH"] = str(PROJECT / "strategy")
    env["MPLCONFIGDIR"] = "/tmp/matplotlib"

    cmd = [
        str(PROJECT / ".venv" / "bin" / "rqalpha"),
        "run",
        "-d", BUNDLE,
        "-f", str(PROJECT / "scripts" / "rqalpha_target_weight_demo.py"),
        "-s", start,
        "-e", end,
        "-a", "stock", str(CASH),
        "-bm", BENCHMARK,
        "-sp", SLIPPAGE,
        "--stock-t1",
        "-o", str(pkl_path),
        "-l", "error",
    ]

    print(f"  Running {strategy['name']}...")
    result = subprocess.run(
        cmd, cwd=str(PROJECT), env=env, capture_output=True, text=True, timeout=600
    )
    if result.returncode != 0:
        print(f"    FAILED: {result.stderr[-200:] if result.stderr else 'unknown'}")
        return {"name": strategy["name"], "label": strategy["label"], "error": True,
                "stderr": result.stderr[-500:] if result.stderr else result.stdout[-500:]}

    try:
        with pkl_path.open("rb") as f:
            pkl = pickle.load(f)
    except Exception as e:
        return {"name": strategy["name"], "label": strategy["label"], "error": True,
                "stderr": str(e)}

    return parse_backtest_result(strategy, pkl)


def parse_backtest_result(strategy: dict, pkl: dict) -> dict:
    """Convert a raw RQAlpha result pickle into a report-ready dict."""
    summary = pkl.get("summary", {})
    portfolio = pkl.get("portfolio")
    trades = pkl.get("trades")
    equity_curve = []
    if portfolio is not None and not portfolio.empty:
        for idx, row in portfolio.iterrows():
            # RQAlpha puts the trading date in the index, not a column.
            equity_curve.append({
                "date": str(idx)[:10],
                "value": round(float(row.get("total_value", 0)), 2),
            })

    # Extract trades with instrument display name
    trade_list = []
    if trades is not None and not trades.empty:
        for _, row in trades.iterrows():
            inst = str(row.get("order_book_id", ""))
            inst_name = CODE_NAMES.get(inst, inst)
            side_val = row.get("side", "")
            if isinstance(side_val, str):
                side_cn = "买入" if side_val == "BUY" else "卖出" if side_val == "SELL" else str(side_val)
            else:
                side_cn = "买入" if side_val == 0 else "卖出" if side_val == 1 else str(side_val)
            trade_list.append({
                "date": str(row.get("datetime", ""))[:10],
                "instrument": inst_name,
                "side": side_cn,
                "quantity": int(row.get("last_quantity", row.get("quantity", 0)) or 0),
                "price": round(float(row.get("last_price", row.get("price", 0)) or 0), 3),
            })

    def _safe_float(val) -> float:
        """Safely convert to float, NaN/inf -> 0."""
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return 0.0
            return f
        except (TypeError, ValueError):
            return 0.0

    return {
        "name": strategy["name"],
        "label": strategy["label"],
        "total_returns": round(_safe_float(summary.get("total_returns")), 4),
        "annualized_returns": round(_safe_float(summary.get("annualized_returns")), 4),
        "sharpe": round(_safe_float(summary.get("sharpe")), 2),
        "max_drawdown": round(_safe_float(summary.get("max_drawdown")), 4),
        "final_value": round(_safe_float(portfolio.iloc[-1]["total_value"] if portfolio is not None and not portfolio.empty else CASH), 2),
        "trade_count": len(trade_list),
        "equity_curve": equity_curve,
        "trades": trade_list[:50],
    }


def render_html(results: list[dict], start: str, end: str) -> str:
    """Generate self-contained HTML report."""
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Sort by total returns descending
    valid = [r for r in results if not r.get("error")]
    errors = [r for r in results if r.get("error")]
    valid.sort(key=lambda x: x["total_returns"], reverse=True)

    # Build comparison table rows
    comparison_rows = ""
    for i, r in enumerate(valid):
        ret = f"{r['total_returns']:+.2%}"
        ret_color = "#52c41a" if r["total_returns"] >= 0 else "#ff4d4f"
        dd = f"{r['max_drawdown']:.2%}"
        highlight = ' style="background:rgba(82,196,26,0.08)"' if i == 0 else ""
        comparison_rows += f"""
        <tr{highlight}>
          <td>{r['label']}（{r['name']}）</td>
          <td style="color:{ret_color};font-weight:600">{ret}</td>
          <td>{r['sharpe']:.2f}</td>
          <td style="color:#ff4d4f">{dd}</td>
          <td>{r['trade_count']}</td>
          <td>¥{r['final_value']:,.0f}</td>
        </tr>"""

    # Build strategy cards
    cards_html = ""
    for r in valid:
        # Equity curve SVG with axes: y = portfolio value (CNY), x = trade date
        ec = r["equity_curve"]
        svg = ""
        if ec:
            values = [e["value"] for e in ec]
            dates = [e["date"] for e in ec]
            min_v, max_v = min(values), max(values)
            pad_v = max((max_v - min_v) * 0.08, 1.0)
            lo, hi = min_v - pad_v, max_v + pad_v
            range_v = hi - lo
            w, h = 1200, 240
            ml, mr, mt, mb = 64, 14, 26, 30  # left/right/top/bottom margins
            pw, ph = w - ml - mr, h - mt - mb
            n = len(ec)
            points = []
            for i, e in enumerate(ec):
                x = ml + (i / max(n - 1, 1)) * pw
                y = mt + ph - ((e["value"] - lo) / range_v) * ph
                points.append(f"{x:.1f},{y:.1f}")
            poly_str = " ".join(points)
            line_color = "#52c41a" if r["total_returns"] >= 0 else "#ff4d4f"
            base_y = mt + ph
            # Horizontal gridlines + y labels (portfolio value in CNY)
            y_ticks = ""
            for k in range(5):
                frac = k / 4.0
                val = lo + range_v * frac
                ty = mt + ph - frac * ph
                y_ticks += (
                    f'<line x1="{ml}" y1="{ty:.1f}" x2="{w - mr}" y2="{ty:.1f}" '
                    f'stroke="#21262d" stroke-width="1"/>'
                    f'<text x="{ml - 6}" y="{ty + 3.5:.1f}" font-size="10" fill="#8b949e" '
                    f'text-anchor="end">{val:,.0f}</text>'
                )
            # X-axis date ticks (up to 6 labels across the backtest window)
            x_ticks = ""
            tick_count = min(6, n)
            for k in range(tick_count):
                idx = round(k * (n - 1) / max(tick_count - 1, 1))
                tx = ml + (idx / max(n - 1, 1)) * pw
                anchor = "start" if k == 0 else ("end" if k == tick_count - 1 else "middle")
                x_ticks += (
                    f'<line x1="{tx:.1f}" y1="{base_y}" x2="{tx:.1f}" y2="{base_y + 4}" '
                    f'stroke="#30363d" stroke-width="1"/>'
                    f'<text x="{tx:.1f}" y="{base_y + 16}" font-size="10" fill="#8b949e" '
                    f'text-anchor="{anchor}">{dates[idx]}</text>'
                )
            svg = f'''<svg viewBox="0 0 {w} {h}" style="width:100%;height:auto" role="img" aria-label="权益曲线">
              {y_ticks}
              <line x1="{ml}" y1="{mt}" x2="{ml}" y2="{base_y}" stroke="#30363d" stroke-width="1"/>
              <line x1="{ml}" y1="{base_y}" x2="{w - mr}" y2="{base_y}" stroke="#30363d" stroke-width="1"/>
              {x_ticks}
              <polyline points="{poly_str}" fill="none" stroke="{line_color}" stroke-width="1.5"/>
              <polyline points="{ml},{base_y} {poly_str} {ml + pw:.1f},{base_y}" fill="{line_color}" opacity="0.1" stroke="none"/>
              <text x="{ml - 6}" y="12" font-size="10" fill="#8b949e" text-anchor="end">元</text>
            </svg>'''

        # Trades table (collapsed by default; <details> toggle expands it)
        trades_html = ""
        for t in r["trades"][:50]:
            side_color = "#52c41a" if t["side"] == "买入" else "#ff4d4f"
            trades_html += f"""
            <tr>
              <td>{t['date']}</td><td>{t['instrument']}</td>
              <td style="color:{side_color}">{t['side']}</td>
              <td>{t['quantity']:,}</td><td>{t['price']:.3f}</td>
            </tr>"""

        if not trades_html:
            trades_html = '<tr><td colspan="5" style="text-align:center;color:#666">无交易</td></tr>'

        ret_color = "#52c41a" if r["total_returns"] >= 0 else "#ff4d4f"
        cards_html += f"""
        <div class="card">
          <h3>{r['label']}（{r['name']}）</h3>
          <div class="metrics">
            <span class="metric" style="color:{ret_color}">收益 {r['total_returns']:+.2%}</span>
            <span class="metric">夏普 {r['sharpe']:.2f}</span>
            <span class="metric" style="color:#ff4d4f">回撤 {r['max_drawdown']:.2%}</span>
            <span class="metric">终值 ¥{r['final_value']:,.0f}</span>
          </div>
          <div class="equity">{svg}</div>
          <details class="trades-details">
            <summary>交易明细（{r['trade_count']} 笔，展示前 {min(len(r['trades']), 50)} 笔）· 点击展开</summary>
            <table class="trades-table">
              <thead><tr><th>日期</th><th>标的</th><th>方向</th><th>数量</th><th>价格</th></tr></thead>
              <tbody>{trades_html}</tbody>
            </table>
          </details>
        </div>"""

    # Error cards
    for r in errors:
        cards_html += f"""
        <div class="card error">
          <h3>{r['label']}（{r['name']}）</h3>
          <p style="color:#ff4d4f">回测失败</p>
          <pre style="color:#999;font-size:11px;white-space:pre-wrap">{r.get('stderr','')[:300]}</pre>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>策略回测日报</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d1117; color:#c9d1d9; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; padding:20px; }}
h1 {{ color:#58a6ff; margin-bottom:4px; }}
.subtitle {{ color:#8b949e; font-size:14px; margin-bottom:20px; }}
.summary {{ background:#1a1d24; border-radius:8px; padding:16px; margin-bottom:24px; overflow-x:auto; }}
.summary table {{ border-collapse:collapse; width:100%; }}
.summary th {{ color:#8b949e; font-size:12px; text-align:left; padding:8px 12px; border-bottom:1px solid #30363d; }}
.summary td {{ padding:8px 12px; border-bottom:1px solid #21262d; font-size:14px; }}
.card {{ background:#1a1d24; border-radius:8px; padding:20px; margin-bottom:20px; border:1px solid #30363d; }}
.card.error {{ border-color:#ff4d4f; }}
.card h3 {{ color:#58a6ff; margin-bottom:12px; }}
.tag {{ font-size:11px; color:#8b949e; background:#21262d; padding:2px 8px; border-radius:10px; font-weight:normal; }}
.metrics {{ display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap; }}
.metric {{ background:#21262d; padding:4px 12px; border-radius:4px; font-size:13px; }}
.equity {{ margin:12px 0; background:#0d1117; border-radius:4px; padding:8px; }}
.trades-table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
.trades-table th {{ color:#8b949e; font-size:11px; text-align:left; padding:6px 8px; border-bottom:1px solid #30363d; }}
.trades-table td {{ padding:6px 8px; border-bottom:1px solid #21262d; font-size:12px; }}
.trades-details {{ margin-top:12px; }}
.trades-details summary {{ cursor:pointer; color:#8b949e; font-size:12px; padding:6px 8px; background:#161b22; border:1px solid #30363d; border-radius:4px; user-select:none; }}
.trades-details summary:hover {{ color:#c9d1d9; border-color:#8b949e; }}
.trades-details[open] summary {{ margin-bottom:8px; }}
a {{ color:#58a6ff; text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
</style>
</head>
<body>
<h1>策略回测日报</h1>
<div class="subtitle">生成时间: {report_date} | 回测区间: {start[:4]}-{start[4:6]}-{start[6:8]} ~ {end[:4]}-{end[4:6]}-{end[6:8]} | 初始资金: ¥{CASH:,}</div>

<div class="summary">
  <table>
    <thead><tr><th>策略</th><th>总收益</th><th>夏普</th><th>最大回撤</th><th>交易次数</th><th>最终市值</th></tr></thead>
    <tbody>{comparison_rows}</tbody>
  </table>
</div>

{cards_html}

<p style="text-align:center;margin-top:24px"><a href="/">← 返回首页</a></p>
</body>
</html>"""


def update_bundle() -> str | None:
    """Incrementally update RQAlpha bundle with latest Tushare data.

    Returns the latest trade date available after update, or None on failure.
    """
    _, last_date = get_bundle_date_range()
    today = datetime.now().strftime("%Y%m%d")

    # Already up to date (within 1 day)
    if last_date >= today:
        print(f"Bundle already current ({last_date}), skipping update.")
        return last_date

    start_date = f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:]}"
    end_date = f"{today[:4]}-{today[4:6]}-{today[6:]}"
    print(f"Updating bundle: {start_date} -> {end_date}")

    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        try:
            token = Path("/root/.tushare_token").read_text().strip()
        except Exception:
            pass

    # Write all universe codes + benchmark to a codes file for --codes-file
    codes_file = OUTPUT_DIR / "update_codes.txt"
    # 000001.XSHG (SSE composite) anchors RQAlpha's available_data_range:
    # without fresh data for it the whole backtest is clipped to its last
    # bar. 000300.XSHG is the benchmark.
    all_codes = [item["code"] for item in UNIVERSE] + ["000300.XSHG", "000001.XSHG"]
    codes_file.write_text("\n".join(all_codes), encoding="utf-8")
    print(f"  Codes file: {len(all_codes)} instruments")

    cmd = [
        VENV_PYTHON,
        str(PROJECT / "scripts" / "update_rqalpha_bundle.py"),
        "update",
        "--bundle", BUNDLE,
        "--start", start_date,
        "--end", end_date,
        "--universe", "stock,index,etf",
        "--codes-file", str(codes_file),
        "--rate-limit-per-minute", "60",
    ]
    env = os.environ.copy()
    env["TUSHARE_TOKEN"] = token
    env["PYTHONPATH"] = str(PROJECT / "strategy")
    try:
        result = subprocess.run(cmd, cwd=str(PROJECT), env=env,
                                capture_output=True, text=True, timeout=1200)
        if result.returncode != 0:
            print(f"  Bundle update warning: {result.stderr[-300:] if result.stderr else 'unknown'}")
        else:
            print("  Bundle updated successfully.")
    except subprocess.TimeoutExpired:
        print("  Bundle update timed out, using existing data.")
    except Exception as e:
        print(f"  Bundle update failed: {e}")

    # Return new latest date
    _, new_last = get_bundle_date_range()
    return new_last


def main() -> int:
    # Step 1: Update bundle with latest Tushare data
    update_bundle()

    # Step 2: Compute backtest period from (updated) bundle
    start, end = compute_start_end()
    print(f"Backtest period: {start} ~ {end}")

    results = []
    for strat in STRATEGIES:
        r = run_backtest(strat, start, end)
        if r:
            results.append(r)

    # Generate HTML
    html = render_html(results, start, end)
    html_path = OUTPUT_DIR / "daily_report.html"
    with html_path.open("w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nReport: {html_path} ({html_path.stat().st_size / 1024:.1f} KB)")

    # Generate JSON summary (values already sanitized by _safe_float)
    json_results = [{k: v for k, v in r.items() if k not in ("equity_curve", "trades")}
                   for r in results]
    json_path = OUTPUT_DIR / "daily_report.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"report_date": datetime.now().strftime("%Y-%m-%d"),
                    "backtest_start": start, "backtest_end": end,
                    "strategies": json_results}, f, ensure_ascii=False, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
