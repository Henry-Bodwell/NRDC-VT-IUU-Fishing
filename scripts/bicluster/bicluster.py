#!/usr/bin/env python3
"""
Pipeline with ORIGINAL-column-based items.

- Input (default): ./data.csv
  * First column is Behavior (original strings)
  * Remaining columns are ORIGINAL KDE-like columns (e.g., "KDE6: F_V.Characteristics", etc.)

- Anonymization:
  * Behavior values -> BEH1, BEH2, ...
  * (We also produce a column-anonymized copy with KDE1, KDE2, ... purely for convenience)
  * Save:
      - data_anonymized.csv
      - mappings.json   {"behavior_map": {...}, "kde_map": {...}}  # kde_map = original_col -> KDE# by order

- Items (based on ORIGINAL column order):
  * For column j in ORIGINAL order (starting at 1 after Behavior):
        item_{2j-1}  corresponds to  value==1  of that original column
        item_{2j}    corresponds to  value==2  of that original column
  * Write per row: "BEH# itemX itemY ..." to beh_item_lines.txt
  * Save:
      - item_mapping.json   {"item1": {"original_col": "<orig label>", "value": 1, "kde_anonym": "KDE1"}, ...}
      - beh_item_table.csv  (Behavior, Items)

- Mining (maximal itemsets using mlxtend.fpmax):
  * maximal_itemsets.csv
  * maximal_itemsets_readable.txt
      For each itemset:
        - Echo support,itemset
        - Behaviors: original behavior strings that contain the itemset
        - Original Columns (with values): each item -> "<original column>" (value=1|2)

Requirements:
    pip install pandas mlxtend
"""

import json
from pathlib import Path
from typing import List, Dict
import pandas as pd

INPUT_CSV = Path("./data.csv")
OUT_DIR = Path(".")

# ----------------- Phase 1: Build and apply mappings -----------------


def build_mappings(df: pd.DataFrame):
    behavior_col = df.columns[0]
    behaviors = df[behavior_col].astype(str).unique().tolist()
    beh_map = {b: f"BEH{i+1}" for i, b in enumerate(behaviors)}

    # KDE anonymized map is *by original column order*
    orig_kde_cols = list(df.columns[1:])
    kde_map = {col: f"KDE{i+1}" for i, col in enumerate(orig_kde_cols)}
    return behavior_col, beh_map, kde_map, orig_kde_cols


def apply_anonymization(
    df: pd.DataFrame,
    behavior_col: str,
    beh_map: Dict[str, str],
    kde_map: Dict[str, str],
) -> pd.DataFrame:
    df_anon = df.copy()
    df_anon[behavior_col] = df_anon[behavior_col].map(beh_map)
    df_anon = df_anon.rename(columns=kde_map)
    return df_anon


# ----------------- Phase 2: Items (by ORIGINAL column order) -----------------


def build_item_mapping_by_original(
    orig_kde_cols: List[str], kde_map: Dict[str, str]
) -> Dict[str, Dict[str, str]]:
    """
    Return dict:
      itemN -> {"original_col": <original label>, "value": 1 or 2, "kde_anonym": "KDEj"}
    where item indices increase by original column order, 2 per column (value 1 then value 2).
    """
    item_map = {}
    item_idx = 1
    for orig_col in orig_kde_cols:
        kde_anonym = kde_map[orig_col]  # e.g., KDE1
        item_map[f"item{item_idx}"] = {
            "original_col": orig_col,
            "value": 1,
            "kde_anonym": kde_anonym,
        }
        item_idx += 1
        item_map[f"item{item_idx}"] = {
            "original_col": orig_col,
            "value": 2,
            "kde_anonym": kde_anonym,
        }
        item_idx += 1
    return item_map


def expand_row_to_items_by_original(
    row: pd.Series,
    orig_kde_cols: List[str],
    kde_map: Dict[str, str],
    item_map: Dict[str, Dict[str, str]],
) -> List[str]:
    """
    For each ORIGINAL column in order:
        if row[anonymized col] == 1 -> include the 'item' mapped to (original_col, 1)
        if row[anonymized col] == 2 -> include the 'item' mapped to (original_col, 2)
    """
    # Build reverse lookup: (original_col, value) -> itemX
    rev = {}
    for item, info in item_map.items():
        rev[(info["original_col"], info["value"])] = item

    items = []
    for orig_col in orig_kde_cols:
        anonym_col = kde_map[orig_col]  # e.g., KDEj
        v = row.get(anonym_col, None)
        try:
            if pd.isna(v):
                continue
            vv = int(v)
        except Exception:
            continue
        if vv in (1, 2):
            it = rev.get((orig_col, vv))
            if it:
                items.append(it)
    return items


# ----------------- Phase 3: Mining (FP-Max) -----------------


def mine_maximal_itemsets(lines_path: Path, min_support: float = 0.1) -> pd.DataFrame:
    from mlxtend.preprocessing import TransactionEncoder
    from mlxtend.frequent_patterns import fpmax

    transactions = []
    with lines_path.open() as f:
        for line in f:
            toks = line.strip().split()
            if not toks:
                continue
            # items start from token 2 as "item..."
            items = [t for t in toks[1:] if t.startswith("item")]
            if items:
                transactions.append(items)

    te = TransactionEncoder()
    arr = te.fit(transactions).transform(transactions)
    df_onehot = pd.DataFrame(arr, columns=te.columns_)
    max_df = fpmax(df_onehot, min_support=min_support, use_colnames=True)
    max_df["length"] = max_df["itemsets"].apply(len)
    max_df = max_df.sort_values(
        ["length", "support"], ascending=[False, False]
    ).reset_index(drop=True)
    return max_df[["support", "itemsets"]]


# ----------------- Phase 4: Rendering back to originals -----------------


def invert_behavior_map(beh_map: Dict[str, str]) -> Dict[str, str]:
    return {v: k for k, v in beh_map.items()}  # BEH# -> original behavior


def behaviors_supporting_itemset(
    itemset: List[str], lines_path: Path, beh_inv: Dict[str, str]
) -> List[str]:
    want = set(itemset)
    supports = []
    with lines_path.open() as f:
        for line in f:
            toks = line.strip().split()
            if not toks:
                continue
            beh = toks[0]  # BEH#
            items = set([t for t in toks[1:] if t.startswith("item")])
            if want.issubset(items):
                supports.append(beh_inv.get(beh, beh))
    return supports


def render_itemset_originals(
    itemset: List[str], item_map: Dict[str, Dict[str, str]]
) -> List[str]:
    """
    For each 'itemX', render "<original_col> (value=1|2)".
    """

    # Ensure human-friendly order by numeric item index
    def item_num(s: str) -> int:
        try:
            return int(s.replace("item", ""))
        except Exception:
            return 10**9

    out = []
    for it in sorted(itemset, key=item_num):
        info = item_map.get(it, {})
        orig = info.get("original_col", it)
        val = info.get("value", "?")
        out.append(f"{orig} (value={val})")
    return out


# ----------------- Main -----------------


def main():
    # Load CSV
    df = pd.read_csv(INPUT_CSV)

    # Build mappings
    behavior_col, beh_map, kde_map, orig_kde_cols = build_mappings(df)

    # Apply anonymization (Behavior->BEH#, KDE label->KDE#)
    df_anon = apply_anonymization(df, behavior_col, beh_map, kde_map)

    # Persist anonymized and mappings
    (OUT_DIR / "data_anonymized.csv").write_text(df_anon.to_csv(index=False))
    (OUT_DIR / "mappings.json").write_text(
        json.dumps({"behavior_map": beh_map, "kde_map": kde_map}, indent=2)
    )

    # Build item mapping (by ORIGINAL column order)
    item_map = build_item_mapping_by_original(orig_kde_cols, kde_map)
    (OUT_DIR / "item_mapping.json").write_text(json.dumps(item_map, indent=2))

    # Build beh_item_lines.txt and table
    lines = []
    rows = []
    for _, row in df_anon.iterrows():
        beh = row[behavior_col]
        items = expand_row_to_items_by_original(row, orig_kde_cols, kde_map, item_map)
        lines.append(" ".join([beh] + items))
        rows.append({"Behavior": beh, "Items": " ".join(items)})
    with (OUT_DIR / "beh_item_lines.txt").open("w") as f:
        for line in lines:
            f.write(line + "\n")
    pd.DataFrame(rows).to_csv(OUT_DIR / "beh_item_table.csv", index=False)

    # Mine maximal itemsets
    max_df = mine_maximal_itemsets(OUT_DIR / "beh_item_lines.txt", min_support=0.1)
    max_df.to_csv(OUT_DIR / "maximal_itemsets.csv", index=False)

    # Prepare readable mapping back to originals
    beh_inv = invert_behavior_map(beh_map)

    with (OUT_DIR / "maximal_itemsets_readable.txt").open("w", encoding="utf-8") as f:
        for _, row in max_df.iterrows():
            itemset = sorted(
                list(row["itemsets"]), key=lambda s: int(s.replace("item", ""))
            )
            support = row["support"]
            f.write(
                f'support={support:.6f}, itemsets=frozenset({{{", ".join(repr(i) for i in itemset)}}})\n'
            )
            # Behaviors supporting this itemset (original labels)
            behs = behaviors_supporting_itemset(
                itemset, OUT_DIR / "beh_item_lines.txt", beh_inv
            )
            f.write("Behaviors:\n")
            for b in behs:
                f.write(f"  {b}\n")
            # Original columns with values
            f.write("Original Columns (with values):\n")
            for line in render_itemset_originals(itemset, item_map):
                f.write(f"  {line}\n")
            f.write("\n")

    # Console summary
    print(
        json.dumps(
            {
                "input_rows": int(df.shape[0]),
                "input_cols": int(df.shape[1]),
                "anon_rows": int(df_anon.shape[0]),
                "anon_cols": int(df_anon.shape[1]),
                "num_itemsets": int(max_df.shape[0]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
