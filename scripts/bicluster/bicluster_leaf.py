#!/usr/bin/env python3
"""Maximal frequent itemset mining over leaf_presence.csv.

Input: scripts/data/leaf_presence.csv (or similar) with columns:
    incident_id, iuu_types, iuu_subtypes, <leaf_path_1>, <leaf_path_2>, ...

Transactions: one per (row, subtype) pair. The row's label column is split on
";". Rows whose label column is empty after splitting are skipped. Each
transaction's items are the leaf-path columns whose value is 1 for that row.

Outputs (in --output-dir):
    leaf_transactions.jsonl
    leaf_maximal_itemsets.csv
    leaf_maximal_itemsets_readable.txt
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
DEFAULT_SKIP_COLS = "incident_id,iuu_types,iuu_subtypes"
DEFAULT_MIN_SUPPORT = 0.1


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
    df: pd.DataFrame, label_col: str, feature_cols: list[str]
) -> tuple[list[dict], int]:
    transactions: list[dict] = []
    skipped = 0
    for _, row in df.iterrows():
        subtypes = parse_labels(row.get(label_col))
        if not subtypes:
            skipped += 1
            continue
        items = row_to_items(row, feature_cols)
        for subtype in subtypes:
            transactions.append({"subtype": subtype, "items": items})
    return transactions, skipped


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


def write_readable(
    out_path: Path,
    max_df: pd.DataFrame,
    transactions: list[dict],
) -> None:
    with out_path.open("w", encoding="utf-8") as fh:
        for _, row in max_df.iterrows():
            itemset = sorted(row["itemsets"])
            support = float(row["support"])
            counter: Counter[str] = Counter()
            n_supporting = 0
            want = set(itemset)
            for tx in transactions:
                if want.issubset(tx["items"]):
                    counter[tx["subtype"]] += 1
                    n_supporting += 1
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
    parser.add_argument(
        "--skip-cols",
        default=DEFAULT_SKIP_COLS,
        help="Comma-separated columns to exclude from feature set.",
    )
    parser.add_argument("--min-support", type=float, default=DEFAULT_MIN_SUPPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    skip_cols = {c.strip() for c in args.skip_cols.split(",") if c.strip()}

    df = pd.read_csv(args.input)
    if args.label_col not in df.columns:
        raise SystemExit(
            f"Label column '{args.label_col}' not found in {args.input}. "
            f"Available: {list(df.columns)[:10]}..."
        )

    feature_cols = [c for c in df.columns if c not in skip_cols]
    transactions, skipped = build_transactions(df, args.label_col, feature_cols)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    tx_path = args.output_dir / "leaf_transactions.jsonl"
    with tx_path.open("w", encoding="utf-8") as fh:
        for tx in transactions:
            fh.write(json.dumps(tx) + "\n")

    max_df = mine_maximal((tx["items"] for tx in transactions), args.min_support)

    csv_path = args.output_dir / "leaf_maximal_itemsets.csv"
    if max_df.empty:
        pd.DataFrame(columns=["support", "itemsets"]).to_csv(csv_path, index=False)
    else:
        export = max_df[["support", "itemsets"]].copy()
        export["itemsets"] = export["itemsets"].apply(lambda s: sorted(s))
        export.to_csv(csv_path, index=False)

    readable_path = args.output_dir / "leaf_maximal_itemsets_readable.txt"
    if max_df.empty:
        readable_path.write_text(
            "(no itemsets at given min_support)\n", encoding="utf-8"
        )
    else:
        write_readable(readable_path, max_df, transactions)

    summary = {
        "input": str(args.input),
        "input_rows": int(df.shape[0]),
        "feature_columns": len(feature_cols),
        "label_column": args.label_col,
        "transactions_emitted": len(transactions),
        "transactions_skipped": skipped,
        "min_support": args.min_support,
        "num_maximal_itemsets": int(max_df.shape[0]) if not max_df.empty else 0,
        "output_dir": str(args.output_dir),
    }
    (args.output_dir / "leaf_run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
