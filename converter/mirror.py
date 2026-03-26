"""Mirror UP (YES) NPZ data to DOWN (NO) NPZ.

Based on CTF matching mechanics:
  UP BID @$p  <->  DOWN ASK @$(1-p)
  UP ASK @$p  <->  DOWN BID @$(1-p)

Usage:
    python -m converter.mirror input_up.npz output_down.npz
"""

import sys
import os
import numpy as np

# Event flags
BUY_DEPTH     = 0xE0000001
SELL_DEPTH    = 0xD0000001
BUY_TRADE     = 0xE0000002
SELL_TRADE    = 0xD0000002
BUY_SNAPSHOT  = 0xE0000004
SELL_SNAPSHOT = 0xD0000004
INIT_CLEAR    = 0xC0000003

# Mapping: UP event -> DOWN event (swap BUY <-> SELL)
MIRROR_MAP = {
    BUY_DEPTH:     SELL_DEPTH,
    SELL_DEPTH:    BUY_DEPTH,
    BUY_TRADE:     SELL_TRADE,
    SELL_TRADE:    BUY_TRADE,
    BUY_SNAPSHOT:  SELL_SNAPSHOT,
    SELL_SNAPSHOT: BUY_SNAPSHOT,
    INIT_CLEAR:    INIT_CLEAR,
}


def mirror_npz(input_path: str, output_path: str = None) -> str:
    """Convert UP NPZ to DOWN NPZ by flipping prices and sides."""
    if output_path is None:
        base, ext = os.path.splitext(input_path)
        output_path = base + "_down.npz"

    data = np.load(input_path)["data"].copy()

    # Flip prices: px' = 1 - px (skip rows where px == 0, e.g. INIT_CLEAR)
    mask = data["px"] > 0
    data["px"][mask] = np.round(1.0 - data["px"][mask], 4)

    # Swap BUY <-> SELL event flags
    for old_ev, new_ev in MIRROR_MAP.items():
        data["ev"][data["ev"] == old_ev] = new_ev

    np.savez_compressed(output_path, data=data)

    print(f"Mirrored: {input_path} -> {output_path}")
    print(f"  Events: {len(data)}")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m converter.mirror <up.npz> [down.npz]")
        sys.exit(1)

    in_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    mirror_npz(in_path, out_path)
