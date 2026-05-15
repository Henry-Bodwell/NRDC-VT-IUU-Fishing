#!/usr/bin/env python3
"""Maximal frequent itemset mining over leaf_presence.csv, two buckets.

Input: scripts/data/leaf_presence.csv (or similar) with columns:
    incident_id, iuu_types, iuu_subtypes, <leaf_path_1>, <leaf_path_2>, ...

Transactions: one per (row, subtype, type) triple. The transaction unit and
label are still the row's subtype; the type determines which mining bucket
it lands in. Rows whose ``iuu_subtypes`` is empty are skipped. Rows whose
``iuu_types`` consists entirely of the excluded type (default: "Other") are
skipped.

Mining is performed in exactly two buckets:
    1. ``--illegal-type`` (default: "Illegal Fishing") — its own bucket.
    2. "Other IUU Types" — every other (non-excluded) type, pooled.

Each bucket has its own min-support flag (``--min-support-illegal`` and
``--min-support-other``) so the dominant Illegal Fishing patterns can be
tuned independently from the long tail.

Outputs (in --output-dir):
    leaf_transactions.jsonl
    leaf_maximal_itemsets.csv          (concatenated, with ``type`` column)
    leaf_maximal_itemsets_readable.txt (grouped by bucket)
    leaf_run_summary.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_INPUT = Path("scripts/data/leaf_presence.csv")
DEFAULT_OUTPUT_DIR = Path("scripts/bicluster/leaf_out")
DEFAULT_LABEL_COL = "iuu_subtypes"
DEFAULT_TYPE_COL = "iuu_types"
DEFAULT_EXCLUDE_TYPE = "Other"
DEFAULT_SKIP_COLS = "incident_id,iuu_types,iuu_subtypes"
DEFAULT_ILLEGAL_TYPE = "Illegal Fishing"
DEFAULT_MIN_SUPPORT_ILLEGAL = 0.1
DEFAULT_MIN_SUPPORT_OTHER = 0.1
DEFAULT_MIN_COUNT = 2
DEFAULT_MIN_LENGTH = 1

OTHER_BUCKET = "Other IUU Types"


def parse_labels(raw: object) -> list[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    return [s.strip() for s in str(raw).split(";") if s.strip()]


def row_to_items(row: pd.Series, feature_cols: list[str]) -> list[str]:
    items: list[str] = []
    for col in feature_cols:
        v = row[col]
        try:
            if int(v) == 1:
                items.append(col)
        except (ValueError, TypeError):
            continue
    return items


def build_transactions(
    df: pd.DataFrame,
    label_col: str,
    type_col: str,
    exclude_type: str,
    feature_cols: list[str],
) -> tuple[list[dict], dict[str, int]]:
    transactions: list[dict] = []
    skipped_no_label = 0
    skipped_no_type = 0
    skipped_type_excluded = 0
    for _, row in df.iterrows():
        types = parse_labels(row.get(type_col))
        if not types:
            skipped_no_type += 1
            continue
        if exclude_type and all(t == exclude_type for t in types):
            skipped_type_excluded += 1
            continue
        kept_types = [t for t in types if t != exclude_type]
        subtypes = parse_labels(row.get(label_col))
        if not subtypes:
            skipped_no_label += 1
            continue
        items = row_to_items(row, feature_cols)
        for t in kept_types:
            for subtype in subtypes:
                transactions.append(
                    {"type": t, "subtype": subtype, "items": items}
                )
    return transactions, {
        "no_label": skipped_no_label,
        "no_type": skipped_no_type,
        "type_excluded": skipped_type_excluded,
    }


def mine_maximal(transactions: Iterable[list[str]], min_support: float) -> pd.DataFrame:
    from mlxtend.preprocessing import TransactionEncoder
    from mlxtend.frequent_patterns import fpmax

    tx_list = [t for t in transactions if t]
    te = TransactionEncoder()
    arr = te.fit(tx_list).transform(tx_list)
    onehot = pd.DataFrame(arr, columns=te.columns_)
    result = fpmax(onehot, min_support=min_support, use_colnames=True)
    if result.empty:
        return result.assign(length=[])
    result["length"] = result["itemsets"].apply(len)
    result = result.sort_values(
        ["length", "support"], ascending=[False, False]
    ).reset_index(drop=True)
    return result


def group_transactions_two_way(
    transactions: list[dict],
    illegal_type: str,
) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {illegal_type: [], OTHER_BUCKET: []}
    for tx in transactions:
        bucket = illegal_type if tx["type"] == illegal_type else OTHER_BUCKET
        grouped[bucket].append(tx)
    return grouped


def mine_buckets(
    grouped: dict[str, list[dict]],
    min_support_by_bucket: dict[str, float],
    min_count: int,
    min_length: int,
) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for bucket_name, txs in grouped.items():
        n = len(txs)
        min_support = min_support_by_bucket[bucket_name]
        if n < min_count:
            results[bucket_name] = {
                "n_transactions": n,
                "effective_min_support": None,
                "itemsets": pd.DataFrame(columns=["support", "itemsets", "length"]),
                "transactions": txs,
                "skipped_reason": f"fewer than min_count={min_count} transactions",
            }
            continue
        effective = max(min_support, min_count / n)
        effective = min(effective, 1.0)
        df = mine_maximal((tx["items"] for tx in txs), effective)
        if not df.empty and min_length > 1:
            df = df[df["length"] >= min_length].reset_index(drop=True)
        results[bucket_name] = {
            "n_transactions": n,
            "effective_min_support": effective,
            "itemsets": df,
            "transactions": txs,
            "skipped_reason": None,
        }
    return results


def itemset_subtype_counts(
    itemset: Iterable[str], transactions: list[dict]
) -> Counter[str]:
    counter: Counter[str] = Counter()
    want = set(itemset)
    for tx in transactions:
        if want.issubset(tx["items"]):
            counter[tx["subtype"]] += 1
    return counter


def format_subtype_counts(counter: Counter[str]) -> str:
    return ";".join(f"{subtype}:{count}" for subtype, count in counter.most_common())


def write_readable(out_path: Path, per_type: dict[str, dict]) -> None:
    ordered = sorted(
        per_type.items(), key=lambda kv: kv[1]["n_transactions"], reverse=True
    )
    with out_path.open("w", encoding="utf-8") as fh:
        for type_name, info in ordered:
            n = info["n_transactions"]
            df = info["itemsets"]
            eff = info["effective_min_support"]
            fh.write(f"=== type: {type_name} ===\n")
            fh.write(f"n_transactions={n}")
            if eff is not None:
                fh.write(f", effective_min_support={eff:.6f}")
            if info["skipped_reason"]:
                fh.write(f", skipped: {info['skipped_reason']}")
            fh.write("\n\n")
            if df.empty:
                fh.write("(no itemsets)\n\n")
                continue
            txs = info["transactions"]
            for _, row in df.iterrows():
                itemset = sorted(row["itemsets"])
                support = float(row["support"])
                counter = itemset_subtype_counts(itemset, txs)
                n_supporting = sum(counter.values())
                fh.write(
                    f"support={support:.6f}, n_supporting={n_supporting}, "
                    f"size={len(itemset)}\n"
                )
                fh.write("items:\n")
                for it in itemset:
                    fh.write(f"  {it}\n")
                fh.write("subtypes (count desc):\n")
                for subtype, count in counter.most_common():
                    fh.write(f"  {count}  {subtype}\n")
                fh.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label-col", default=DEFAULT_LABEL_COL)
    parser.add_argument("--type-col", default=DEFAULT_TYPE_COL)
    parser.add_argument(
        "--exclude-type",
        default=DEFAULT_EXCLUDE_TYPE,
        help=(
            "Drop rows whose iuu_types is entirely this value, and never "
            "form a mining group for it. Pass empty string to disable."
        ),
    )
    parser.add_argument(
        "--skip-cols",
        default=DEFAULT_SKIP_COLS,
        help="Comma-separated columns to exclude from feature set.",
    )
    parser.add_argument(
        "--illegal-type",
        default=DEFAULT_ILLEGAL_TYPE,
        help=(
            "IUU type that gets its own mining bucket. Every other "
            "non-excluded type is pooled into the 'Other IUU Types' bucket."
        ),
    )
    parser.add_argument(
        "--min-support-illegal",
        type=float,
        default=DEFAULT_MIN_SUPPORT_ILLEGAL,
        help="min_support for the Illegal Fishing bucket.",
    )
    parser.add_argument(
        "--min-support-other",
        type=float,
        default=DEFAULT_MIN_SUPPORT_OTHER,
        help="min_support for the Other IUU Types bucket.",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=DEFAULT_MIN_COUNT,
        help=(
            "Absolute floor on supporting transactions per itemset. "
            "Effective min_support is max(bucket min_support, min_count / N). "
            "Buckets with N < min_count are skipped."
        ),
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=DEFAULT_MIN_LENGTH,
        help="Drop maximal itemsets with fewer than this many items.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    skip_cols = {c.strip() for c in args.skip_cols.split(",") if c.strip()}

    df = pd.read_csv(args.input)
    for col in (args.label_col, args.type_col):
        if col not in df.columns:
            raise SystemExit(
                f"Column '{col}' not found in {args.input}. "
                f"Available: {list(df.columns)[:10]}..."
            )

    feature_cols = [c for c in df.columns if c not in skip_cols]
    transactions, skipped = build_transactions(
        df, args.label_col, args.type_col, args.exclude_type, feature_cols
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    tx_path = args.output_dir / "leaf_transactions.jsonl"
    with tx_path.open("w", encoding="utf-8") as fh:
        for tx in transactions:
            fh.write(json.dumps(tx) + "\n")

    grouped = group_transactions_two_way(transactions, args.illegal_type)
    min_support_by_bucket = {
        args.illegal_type: args.min_support_illegal,
        OTHER_BUCKET: args.min_support_other,
    }
    per_type = mine_buckets(
        grouped, min_support_by_bucket, args.min_count, args.min_length
    )

    csv_path = args.output_dir / "leaf_maximal_itemsets.csv"
    csv_columns = [
        "type",
        "n_transactions",
        "support",
        "n_supporting",
        "itemsets",
        "subtype_counts",
    ]
    frames: list[pd.DataFrame] = []
    for type_name, info in per_type.items():
        df_t = info["itemsets"]
        if df_t.empty:
            continue
        txs = info["transactions"]
        sorted_items = df_t["itemsets"].apply(sorted)
        counters = [itemset_subtype_counts(items, txs) for items in sorted_items]
        export = pd.DataFrame(
            {
                "type": type_name,
                "n_transactions": info["n_transactions"],
                "support": df_t["support"].values,
                "n_supporting": [sum(c.values()) for c in counters],
                "itemsets": sorted_items.values,
                "subtype_counts": [format_subtype_counts(c) for c in counters],
            }
        )
        frames.append(export)
    if frames:
        pd.concat(frames, ignore_index=True)[csv_columns].to_csv(csv_path, index=False)
    else:
        pd.DataFrame(columns=csv_columns).to_csv(csv_path, index=False)

    readable_path = args.output_dir / "leaf_maximal_itemsets_readable.txt"
    if not per_type:
        readable_path.write_text("(no transactions)\n", encoding="utf-8")
    else:
        write_readable(readable_path, per_type)

    summary = {
        "input": str(args.input),
        "input_rows": int(df.shape[0]),
        "feature_columns": len(feature_cols),
        "label_column": args.label_col,
        "type_column": args.type_col,
        "exclude_type": args.exclude_type,
        "transactions_emitted": len(transactions),
        "transactions_skipped": skipped,
        "illegal_type": args.illegal_type,
        "min_support_illegal": args.min_support_illegal,
        "min_support_other": args.min_support_other,
        "min_count": args.min_count,
        "min_length": args.min_length,
        "types": {
            name: {
                "n_transactions": info["n_transactions"],
                "effective_min_support": info["effective_min_support"],
                "num_maximal_itemsets": int(info["itemsets"].shape[0]),
                "skipped_reason": info["skipped_reason"],
            }
            for name, info in per_type.items()
        },
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "leaf_run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
