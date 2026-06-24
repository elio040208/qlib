# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Evaluate formulaic alpha factors with Qlib data.

This script is intentionally model-free. It ranks interpretable expressions by
single-factor IC, Rank IC, long-short return, coverage, and score autocorrelation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
import qlib
import yaml
from qlib.constant import REG_CN, REG_TW, REG_US
from qlib.contrib.eva.alpha import calc_ic, calc_long_short_return, pred_autocorr
from qlib.data.dataset.loader import QlibDataLoader


REGION_MAP = {
    "cn": REG_CN,
    "us": REG_US,
    "tw": REG_TW,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate traditional formulaic alpha factors.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("factor_pool.yaml"),
        help="YAML config containing data, periods, label, and factor expressions.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for CSV and Markdown reports. Overrides output.dir in config.",
    )
    parser.add_argument(
        "--segments",
        nargs="*",
        default=None,
        help="Optional subset of configured periods to evaluate, for example: valid test.",
    )
    return parser.parse_args()


def load_config(path: Path) -> Dict[str, Any]:
    with path.expanduser().open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate_config(cfg)
    return cfg


def validate_config(cfg: Dict[str, Any]) -> None:
    names = [factor["name"] for factor in cfg["factors"]]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise ValueError(f"Duplicated factor names: {duplicated}")
    if cfg["evaluation"].get("direction_policy", "train_ic") not in {"train_ic", "as_is"}:
        raise ValueError("evaluation.direction_policy must be 'train_ic' or 'as_is'")


def init_qlib(cfg: Dict[str, Any]) -> None:
    qlib_cfg = cfg["qlib"]
    region_name = qlib_cfg.get("region", "cn").lower()
    if region_name not in REGION_MAP:
        raise ValueError(f"Unsupported qlib.region: {region_name}")
    qlib.init(provider_uri=qlib_cfg["provider_uri"], region=REGION_MAP[region_name])


def get_load_range(periods: Dict[str, List[str]]) -> Tuple[str, str]:
    starts = [pd.Timestamp(v[0]) for v in periods.values()]
    ends = [pd.Timestamp(v[1]) for v in periods.values()]
    return min(starts).strftime("%Y-%m-%d"), max(ends).strftime("%Y-%m-%d")


def load_factor_frame(cfg: Dict[str, Any]) -> pd.DataFrame:
    factors = cfg["factors"]
    label = cfg["label"]
    start_time, end_time = get_load_range(cfg["periods"])
    loader = QlibDataLoader(
        config={
            "feature": ([factor["expression"] for factor in factors], [factor["name"] for factor in factors]),
            "label": ([label["expression"]], [label["name"]]),
        },
        freq=cfg["universe"].get("freq", "day"),
    )
    return loader.load(cfg["universe"]["market"], start_time=start_time, end_time=end_time)


def slice_segment(obj: pd.DataFrame | pd.Series, start: str, end: str) -> pd.DataFrame | pd.Series:
    dt = obj.index.get_level_values("datetime")
    mask = (dt >= pd.Timestamp(start)) & (dt <= pd.Timestamp(end))
    return obj.loc[mask]


def safe_ir(series: pd.Series, ann_scaler: float = 1.0) -> float:
    series = series.dropna()
    std = series.std()
    if len(series) == 0 or std == 0 or pd.isna(std):
        return np.nan
    return float(series.mean() / std * np.sqrt(ann_scaler))


def coverage(score: pd.Series, label: pd.Series) -> float:
    pair = pd.concat({"score": score, "label": label}, axis=1)
    if pair.empty:
        return np.nan
    return float(pair.dropna().shape[0] / pair.shape[0])


def mean_autocorr(score: pd.Series) -> float:
    score = score.dropna()
    if score.empty:
        return np.nan
    try:
        return float(pred_autocorr(score).mean())
    except Exception:
        return np.nan


def calc_direction(raw_score: pd.Series, label: pd.Series, policy: str, configured_direction: Any = None) -> Tuple[int, float]:
    if configured_direction is not None:
        direction = int(configured_direction)
        if direction not in {-1, 1}:
            raise ValueError(f"Configured factor direction must be -1 or 1, got {configured_direction}")
        raw_ic, _ = calc_ic(raw_score, label, dropna=True)
        return direction, float(raw_ic.mean())

    raw_ic, _ = calc_ic(raw_score, label, dropna=True)
    raw_ic_mean = float(raw_ic.mean())
    if policy == "as_is" or pd.isna(raw_ic_mean) or raw_ic_mean >= 0:
        return 1, raw_ic_mean
    return -1, raw_ic_mean


def evaluate_one(score: pd.Series, label: pd.Series, quantile: float, ann_scaler: float) -> Tuple[Dict[str, float], pd.DataFrame]:
    ic, rank_ic = calc_ic(score, label, dropna=True)
    long_short, long_avg = calc_long_short_return(score, label, quantile=quantile, dropna=True)
    metrics = {
        "ic_mean": float(ic.mean()),
        "ic_std": float(ic.std()),
        "icir": safe_ir(ic),
        "rank_ic_mean": float(rank_ic.mean()),
        "rank_ic_std": float(rank_ic.std()),
        "rank_icir": safe_ir(rank_ic),
        "positive_ic_rate": float((ic > 0).mean()) if len(ic) else np.nan,
        "long_short_mean": float(long_short.mean()),
        "long_short_ann": float(long_short.mean() * ann_scaler),
        "long_short_ir": safe_ir(long_short, ann_scaler=ann_scaler),
        "long_avg_mean": float(long_avg.mean()),
        "coverage": coverage(score, label),
        "autocorr_1": mean_autocorr(score),
        "n_dates": int(ic.shape[0]),
        "n_obs": int(pd.concat({"score": score, "label": label}, axis=1).dropna().shape[0]),
    }
    daily = pd.DataFrame(
        {
            "ic": ic,
            "rank_ic": rank_ic,
            "long_short_return": long_short,
            "long_average_return": long_avg,
        }
    )
    daily.index.name = "datetime"
    return metrics, daily


def flatten_metrics(prefix: str, metrics: Dict[str, float]) -> Dict[str, float]:
    return {f"{prefix}_{k}": v for k, v in metrics.items()}


def evaluate_factors(cfg: Dict[str, Any], data: pd.DataFrame, selected_segments: Iterable[str] | None = None):
    feature = data["feature"]
    label = data["label"][cfg["label"]["name"]]
    periods = cfg["periods"]
    if selected_segments is not None:
        periods = {k: periods[k] for k in selected_segments}
    train_start, train_end = cfg["periods"]["train"]
    train_label = slice_segment(label, train_start, train_end)
    eval_cfg = cfg["evaluation"]
    quantile = float(eval_cfg.get("quantile", 0.2))
    ann_scaler = float(eval_cfg.get("ann_scaler", 252))
    direction_policy = eval_cfg.get("direction_policy", "train_ic")

    rows = []
    daily_rows = []
    for factor in cfg["factors"]:
        name = factor["name"]
        raw_score = feature[name]
        train_score = slice_segment(raw_score, train_start, train_end)
        direction, train_raw_ic_mean = calc_direction(
            train_score,
            train_label,
            direction_policy,
            configured_direction=factor.get("direction"),
        )
        score = raw_score * direction
        row: Dict[str, Any] = {
            "factor": name,
            "category": factor.get("category", ""),
            "direction": direction,
            "train_raw_ic_mean": train_raw_ic_mean,
            "expression": factor["expression"],
            "hypothesis": factor.get("hypothesis", ""),
        }
        for segment, (start, end) in periods.items():
            seg_score = slice_segment(score, start, end)
            seg_label = slice_segment(label, start, end)
            metrics, daily = evaluate_one(seg_score, seg_label, quantile=quantile, ann_scaler=ann_scaler)
            row.update(flatten_metrics(segment, metrics))
            daily = daily.reset_index()
            daily.insert(0, "segment", segment)
            daily.insert(1, "factor", name)
            daily_rows.append(daily)
        rows.append(row)

    metrics_df = pd.DataFrame(rows)
    daily_df = pd.concat(daily_rows, ignore_index=True) if daily_rows else pd.DataFrame()
    metrics_df = apply_selection(metrics_df, cfg)
    return metrics_df, daily_df


def apply_selection(metrics_df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    eval_cfg = cfg["evaluation"]
    segment = eval_cfg.get("selection_segment", "valid")
    top_n = int(eval_cfg.get("top_n", 10))
    min_coverage = float(eval_cfg.get("min_coverage", 0.7))

    score_col = f"{segment}_rank_icir"
    mean_col = f"{segment}_rank_ic_mean"
    coverage_col = f"{segment}_coverage"
    if score_col not in metrics_df.columns:
        metrics_df["selected"] = False
        metrics_df["selection_rank"] = np.nan
        metrics_df["selection_score"] = np.nan
        return metrics_df

    eligible = metrics_df[coverage_col].fillna(0) >= min_coverage
    if mean_col in metrics_df.columns:
        eligible &= metrics_df[mean_col].fillna(-np.inf) > 0

    ranked = metrics_df.loc[eligible].sort_values(
        by=[score_col, mean_col],
        ascending=[False, False],
        na_position="last",
    )
    selected = ranked.head(top_n)["factor"].tolist()
    rank_map = {factor: rank + 1 for rank, factor in enumerate(ranked["factor"].tolist())}

    metrics_df["selected"] = metrics_df["factor"].isin(selected)
    metrics_df["selection_rank"] = metrics_df["factor"].map(rank_map)
    metrics_df["selection_score"] = metrics_df[score_col]
    return metrics_df.sort_values(["selected", "selection_rank", "factor"], ascending=[False, True, True])


def fmt(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{value:.6g}"
    return str(value)


def markdown_table(df: pd.DataFrame, columns: List[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = ["| " + " | ".join(fmt(row[col]) for col in columns) + " |" for _, row in df[columns].iterrows()]
    return "\n".join([header, sep] + rows)


def write_report(metrics_df: pd.DataFrame, cfg: Dict[str, Any], output_dir: Path) -> None:
    segment = cfg["evaluation"].get("selection_segment", "valid")
    top = metrics_df[metrics_df["selected"]].copy()
    cols = [
        "selection_rank",
        "factor",
        "category",
        "direction",
        f"{segment}_rank_ic_mean",
        f"{segment}_rank_icir",
        f"{segment}_long_short_ann",
        f"{segment}_long_short_ir",
        f"{segment}_coverage",
    ]
    cols = [c for c in cols if c in top.columns]

    lines = [
        "# Alpha Factor Mining Report",
        "",
        f"Market: `{cfg['universe']['market']}`",
        f"Label: `{cfg['label']['expression']}`",
        f"Selection segment: `{segment}`",
        "",
        "## Selected Factors",
        "",
    ]
    if top.empty:
        lines.append("No factor passed the selection filters.")
    else:
        lines.append(markdown_table(top, cols))
    lines += [
        "",
        "## Method",
        "",
        "- Direction is learned from train IC unless a factor defines `direction` explicitly.",
        "- Selection ranks factors by Rank ICIR on the configured selection segment.",
        "- Long-short return uses the configured top/bottom quantile.",
        "- Test-period metrics are reported in CSV but are not used for selection.",
        "",
        "## Files",
        "",
        "- `factor_metrics.csv`: one row per factor with train/valid/test metrics.",
        "- `factor_daily_metrics.csv`: daily IC, Rank IC, and long-short return.",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    init_qlib(cfg)
    output_dir = args.output_dir or Path(cfg.get("output", {}).get("dir", "/tmp/qlib_alpha_factor_mining"))
    output_dir = output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    data = load_factor_frame(cfg)
    metrics_df, daily_df = evaluate_factors(cfg, data, selected_segments=args.segments)
    metrics_df.to_csv(output_dir / "factor_metrics.csv", index=False)
    daily_df.to_csv(output_dir / "factor_daily_metrics.csv", index=False)
    write_report(metrics_df, cfg, output_dir)

    selected = metrics_df.loc[metrics_df["selected"], "factor"].tolist()
    print(f"Loaded {len(cfg['factors'])} factors and wrote results to {output_dir}")
    print(f"Selected factors: {', '.join(selected) if selected else 'none'}")


if __name__ == "__main__":
    main()
