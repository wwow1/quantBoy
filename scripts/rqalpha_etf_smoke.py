#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal RQAlpha smoke strategy.

Run with:
    .venv/bin/rqalpha run \
      -d data/rqalpha_bundle/bundle \
      -f scripts/rqalpha_etf_smoke.py \
      -s 2020-11-16 \
      -e 2026-03-20 \
      -a stock 1000000 \
      -bm 000300.XSHG \
      -mt next_bar \
      -sp 0.001 \
      --stock-t1 \
      --report /tmp/rqalpha_etf_smoke_report.csv \
      -o /tmp/rqalpha_etf_smoke.pkl
"""

from rqalpha.apis import order_percent, update_universe


def init(context):
    context.asset = "510300.XSHG"
    context.fired = False
    update_universe(context.asset)


def handle_bar(context, bar_dict):
    if context.fired:
        return
    order_percent(context.asset, 0.99)
    context.fired = True
