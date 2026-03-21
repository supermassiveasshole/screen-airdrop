"""Compare gray4 and layered vNext frame capacities."""

from __future__ import annotations

import argparse

from screen_airdrop.common.protocol_layered import (
    LAYERED_BODY_PROFILE_DENSE,
    LAYERED_BODY_PROFILE_ROBUST,
)
from screen_airdrop.sender.encoder_gray4 import frame_capacity_bytes_gray4
from screen_airdrop.sender.encoder_layered import frame_capacity_bytes_layered


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare gray4 and layered vNext capacities.")
    parser.add_argument("--grid", default="240x144", help="Module grid, e.g. 240x144")
    parser.add_argument("--guard-band", type=int, default=1)
    parser.add_argument("--corner-size", type=int, default=7)
    parser.add_argument("--gray4-ecc", default="L")
    args = parser.parse_args()

    grid_w, grid_h = (int(part) for part in str(args.grid).lower().split("x", 1))
    gray4 = frame_capacity_bytes_gray4(
        grid_w=grid_w,
        grid_h=grid_h,
        ecc_level=str(args.gray4_ecc),
        guard_band=int(args.guard_band),
        corner_size=int(args.corner_size),
    )
    dense = frame_capacity_bytes_layered(
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=int(args.guard_band),
        corner_size=int(args.corner_size),
        body_profile_id=LAYERED_BODY_PROFILE_DENSE,
    )
    robust = frame_capacity_bytes_layered(
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=int(args.guard_band),
        corner_size=int(args.corner_size),
        body_profile_id=LAYERED_BODY_PROFILE_ROBUST,
    )
    print(
        {
            "grid": f"{grid_w}x{grid_h}",
            "gray4_payload_cap": gray4,
            "layered_dense_payload_cap": dense,
            "layered_dense_ratio_vs_gray4": round(dense / gray4, 4) if gray4 else 0.0,
            "layered_robust_payload_cap": robust,
            "layered_robust_ratio_vs_gray4": round(robust / gray4, 4) if gray4 else 0.0,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
