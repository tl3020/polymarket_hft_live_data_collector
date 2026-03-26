"""Convert JSONL raw WS data to hftbacktest NPZ format.

Usage:
    python -m converter.jsonl_to_npz data/btc_1h/2026-03-25/some-market.jsonl.gz
    python -m converter.jsonl_to_npz data/btc_1h/2026-03-25/some-market.jsonl
"""

import gzip
import json
import sys
import os
import numpy as np

# hftbacktest event_dtype
EVENT_DTYPE = np.dtype([
    ("ev", "<u8"), ("exch_ts", "<i8"), ("local_ts", "<i8"),
    ("px", "<f8"), ("qty", "<f8"), ("order_id", "<u8"),
    ("ival", "<i8"), ("fval", "<f8"),
])

# Event flags
INIT_CLEAR    = 0xC0000003
BUY_DEPTH     = 0xE0000001
SELL_DEPTH    = 0xD0000001
BUY_TRADE     = 0xE0000002
SELL_TRADE    = 0xD0000002
BUY_SNAPSHOT  = 0xE0000004
SELL_SNAPSHOT = 0xD0000004


def _row(ev, exch_ts, local_ts, px, qty):
    return (ev, exch_ts, local_ts, px, qty, 0, 0, 0.0)


def convert_jsonl_to_npz(input_path: str, output_path: str = None) -> str:
    """Convert a JSONL (or .jsonl.gz) file to hftbacktest NPZ.

    Returns the output path.
    """
    if output_path is None:
        base = input_path
        for ext in (".gz", ".jsonl"):
            if base.endswith(ext):
                base = base[:-len(ext)]
        output_path = base + ".npz"

    # Open file (plain or gzipped)
    if input_path.endswith(".gz"):
        opener = gzip.open(input_path, "rt", encoding="utf-8")
    else:
        opener = open(input_path, "r", encoding="utf-8")

    events = []
    line_count = 0
    error_count = 0

    with opener as f:
        for line in f:
            line_count += 1
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                error_count += 1
                continue

            local_ts = msg.get("local_ts", 0)
            event_type = msg.get("event_type")
            ts_str = msg.get("timestamp", "0")
            exch_ts = int(ts_str) * 1_000_000  # ms -> ns

            if event_type == "book":
                # Initial snapshot: INIT_CLEAR + all levels
                events.append(_row(INIT_CLEAR, exch_ts, local_ts, 0.0, 0.0))
                for bid in msg.get("bids", []):
                    events.append(_row(
                        BUY_SNAPSHOT, exch_ts, local_ts,
                        float(bid["price"]), float(bid["size"]),
                    ))
                for ask in msg.get("asks", []):
                    events.append(_row(
                        SELL_SNAPSHOT, exch_ts, local_ts,
                        float(ask["price"]), float(ask["size"]),
                    ))

            elif event_type == "price_change":
                side = msg.get("side", "").upper()
                ev = BUY_DEPTH if side == "BUY" else SELL_DEPTH
                events.append(_row(
                    ev, exch_ts, local_ts,
                    float(msg["price"]), float(msg["size"]),
                ))

            elif event_type == "last_trade_price":
                side = msg.get("side", "").upper()
                ev = BUY_TRADE if side == "BUY" else SELL_TRADE
                events.append(_row(
                    ev, exch_ts, local_ts,
                    float(msg["price"]), float(msg["size"]),
                ))

    if not events:
        print(f"WARNING: No events found in {input_path}")
        return output_path

    data = np.array(events, dtype=EVENT_DTYPE)
    # Sort by exch_ts for causality
    data.sort(order="exch_ts")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    np.savez_compressed(output_path, data=data)

    print(f"Converted: {input_path}")
    print(f"  Lines: {line_count} | Errors: {error_count}")
    print(f"  Events: {len(data)}")
    print(f"  Output: {output_path}")
    print(f"  Size: {os.path.getsize(output_path) / 1024:.1f} KB")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m converter.jsonl_to_npz <input.jsonl[.gz]> [output.npz]")
        sys.exit(1)

    in_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    convert_jsonl_to_npz(in_path, out_path)
