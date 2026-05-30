"""Shared constants for the one-time BigQuery infra scripts.

Keeping project / location / dataset names in ONE place stops the create_*.py
scripts from drifting apart -- which is exactly how the old "reports" vs
"raw_windsor" mismatch happened. The loaders (windsor_data_pull/*) hardcode the
same names in their own config; keep the two in sync.
"""
PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"

# Shared raw ad-platform performance data (Windsor.ai -> BigQuery).
# Holds perf_the_trade_desk and perf_meta. The loaders write here.
RAW_DATASET = "raw_windsor"
