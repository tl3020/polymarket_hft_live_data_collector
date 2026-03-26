"""Verify NPZ data quality for hftbacktest compatibility.

Checks:
  1. Correct dtype
  2. Required event types present
  3. Timestamps monotonically increasing
  4. Prices and quantities reasonable
  5. hftbacktest can load the data (optional, requires hftbacktest)

Usage:
    python -m converter.verify_npz data.npz
    python -m converter.verify_npz data.npz --hbt   # Also verify with hftbacktest
"""

import sys
import numpy as np

# Event flags
INIT_CLEAR    = 0xC0000003
BUY_DEPTH     = 0xE0000001
SELL_DEPTH    = 0xD0000001
BUY_TRADE     = 0xE0000002
SELL_TRADE    = 0xD0000002
BUY_SNAPSHOT  = 0xE0000004
SELL_SNAPSHOT = 0xD0000004

REQUIRED_EVENTS = {INIT_CLEAR, BUY_SNAPSHOT, SELL_SNAPSHOT}
ALL_KNOWN_EVENTS = {INIT_CLEAR, BUY_DEPTH, SELL_DEPTH, BUY_TRADE, SELL_TRADE,
                    BUY_SNAPSHOT, SELL_SNAPSHOT}

EXPECTED_FIELDS = ("ev", "exch_ts", "local_ts", "px", "qty", "order_id", "ival", "fval")


def verify_npz(path: str, test_hbt: bool = False) -> bool:
    """Verify NPZ data quality. Returns True if all checks pass."""
    print(f"Verifying: {path}")
    passed = True

    data = np.load(path)["data"]
    print(f"  Events: {len(data)}")

    # 1. Dtype check
    if data.dtype.names != EXPECTED_FIELDS:
        print(f"  FAIL: dtype mismatch. Got {data.dtype.names}")
        return False
    print("  OK: dtype correct")

    # 2. Event types
    unique_ev = set(data["ev"].tolist())
    unknown = unique_ev - ALL_KNOWN_EVENTS
    if unknown:
        print(f"  WARN: Unknown event types: {[hex(e) for e in unknown]}")

    missing = REQUIRED_EVENTS - unique_ev
    if missing:
        print(f"  FAIL: Missing required events: {[hex(e) for e in missing]}")
        passed = False
    else:
        print("  OK: Required events present")

    # Event counts
    for ev, name in [
        (INIT_CLEAR, "INIT_CLEAR"), (BUY_SNAPSHOT, "BUY_SNAPSHOT"),
        (SELL_SNAPSHOT, "SELL_SNAPSHOT"), (BUY_DEPTH, "BUY_DEPTH"),
        (SELL_DEPTH, "SELL_DEPTH"), (BUY_TRADE, "BUY_TRADE"),
        (SELL_TRADE, "SELL_TRADE"),
    ]:
        count = int(np.sum(data["ev"] == ev))
        if count > 0:
            print(f"    {name}: {count}")

    # 3. Timestamp monotonicity
    ts_diff = np.diff(data["exch_ts"])
    non_mono = int(np.sum(ts_diff < 0))
    if non_mono > 0:
        print(f"  WARN: {non_mono} non-monotonic exch_ts (may indicate reordering)")
    else:
        print("  OK: exch_ts monotonically increasing")

    # Timestamp range
    if len(data) > 0:
        first_ts = data["exch_ts"][0] / 1e9  # ns -> s
        last_ts = data["exch_ts"][-1] / 1e9
        from datetime import datetime, timezone
        first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)
        last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc)
        duration = last_ts - first_ts
        print(f"  Time range: {first_dt:%Y-%m-%d %H:%M:%S} to {last_dt:%H:%M:%S} ({duration:.0f}s)")

    # 4. Price / quantity checks
    px = data["px"]
    qty = data["qty"]
    # Exclude INIT_CLEAR (px=0, qty=0)
    data_mask = data["ev"] != INIT_CLEAR
    if np.any(data_mask):
        px_valid = px[data_mask]
        qty_valid = qty[data_mask]

        if np.any(px_valid < 0) or np.any(px_valid > 1.0):
            print(f"  WARN: Prices outside [0, 1]: min={px_valid.min():.4f} max={px_valid.max():.4f}")
        else:
            print(f"  OK: Prices in [0, 1] range (min={px_valid.min():.4f} max={px_valid.max():.4f})")

        if np.any(qty_valid < 0):
            print(f"  FAIL: Negative quantities found")
            passed = False
        else:
            print(f"  OK: Quantities non-negative (max={qty_valid.max():.1f})")

    # 5. hftbacktest load test
    if test_hbt:
        try:
            from hftbacktest import BacktestAsset, HashMapMarketDepthBacktest
            asset = (
                BacktestAsset()
                .data([data])
                .linear_asset(1.0)
                .constant_latency(10_000_000, 10_000_000)
                .power_prob_queue_model3(3.0)
                .no_partial_fill_exchange()
                .trading_value_fee_model(0.0, 0.0)
                .tick_size(0.01)
                .lot_size(0.01)
            )
            hbt = HashMapMarketDepthBacktest([asset])
            print("  OK: hftbacktest loaded successfully")
        except ImportError:
            print("  SKIP: hftbacktest not installed")
        except Exception as e:
            print(f"  FAIL: hftbacktest load error: {e}")
            passed = False

    result = "PASSED" if passed else "FAILED"
    print(f"  Result: {result}")
    return passed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m converter.verify_npz <data.npz> [--hbt]")
        sys.exit(1)

    path = sys.argv[1]
    test_hbt = "--hbt" in sys.argv
    ok = verify_npz(path, test_hbt)
    sys.exit(0 if ok else 1)
