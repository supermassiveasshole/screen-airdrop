"""Transfer statistics for realtime and replay receiver flows."""

from __future__ import annotations

import time
from typing import Dict, Optional


class TransferStats(object):
    def __init__(self, start_ts: Optional[float] = None):
        self.start_ts = float(start_ts if start_ts is not None else time.time())
        self.first_data_ts = None  # type: Optional[float]
        self.last_data_ts = None  # type: Optional[float]
        self.done_ts = None  # type: Optional[float]

        self.total_frames = 0
        self.valid_frames = 0
        self.bad_frames = 0
        self.payload_bytes = 0

        self.locator_total = 0
        self.locator_fail = 0
        self.locator_conf_sum = 0.0

        self.roi_mode_used = "auto_then_manual"
        self.manual_roi_applied = False
        self.auto_to_manual_switches = 0
        self.manual_select_attempts = 0

    def set_roi_mode(self, roi_mode: str) -> None:
        self.roi_mode_used = roi_mode

    def mark_manual_roi(self, switched: bool = False) -> None:
        self.manual_roi_applied = True
        if switched:
            self.auto_to_manual_switches += 1

    def mark_manual_select_attempt(self) -> None:
        self.manual_select_attempts += 1

    def on_locator(self, confidence: float, failed: bool) -> None:
        self.locator_total += 1
        self.locator_conf_sum += float(confidence)
        if failed:
            self.locator_fail += 1

    def on_frame(self, decoded_ok: bool, payload_len: int, ts: Optional[float] = None) -> None:
        now = float(ts if ts is not None else time.time())
        self.total_frames += 1
        if decoded_ok:
            self.valid_frames += 1
            if payload_len > 0:
                self.payload_bytes += int(payload_len)
                if self.first_data_ts is None:
                    self.first_data_ts = now
                self.last_data_ts = now
        else:
            self.bad_frames += 1

    def _elapsed(self, now: float) -> float:
        return max(1e-6, now - self.start_ts)

    def snapshot(self, ts: Optional[float] = None) -> Dict[str, float]:
        now = float(ts if ts is not None else time.time())
        elapsed = self._elapsed(now)

        raw_fps = self.total_frames / elapsed
        valid_fps = self.valid_frames / elapsed
        # NOTE: throughput is computed in KiB/s (bytes / 1024 / s).
        goodput_kibps = (self.payload_bytes / elapsed) / 1024.0
        bad_rate = (
            float(self.bad_frames) / float(self.total_frames) if self.total_frames > 0 else 0.0
        )
        recovery_latency = (
            max(0.0, now - self.first_data_ts) if self.first_data_ts is not None else 0.0
        )
        locator_fail_rate = (
            float(self.locator_fail) / float(self.locator_total) if self.locator_total > 0 else 0.0
        )
        locator_conf = (
            self.locator_conf_sum / float(self.locator_total) if self.locator_total > 0 else 0.0
        )

        snap = {
            "raw_frame_rate_fps": raw_fps,
            "valid_frame_rate_fps": valid_fps,
            "goodput_kibps": goodput_kibps,
            "bad_frame_rate": bad_rate,
            "recovery_latency_s": recovery_latency,
            "locator_fail_rate": locator_fail_rate,
            "mean_locator_confidence": locator_conf,
            "total_frames": float(self.total_frames),
            "valid_frames": float(self.valid_frames),
            "bad_frames": float(self.bad_frames),
            "payload_bytes": float(self.payload_bytes),
            "elapsed_s": elapsed,
        }
        # Backward compatibility alias (deprecated).
        snap["goodput_kbps"] = snap["goodput_kibps"]
        return snap

    def finalize(self, output_size_bytes: int = 0, ts: Optional[float] = None) -> Dict[str, float]:
        now = float(ts if ts is not None else time.time())
        self.done_ts = now
        snap = self.snapshot(ts=now)

        total_elapsed = self._elapsed(now)
        end_to_end_kibps = (
            (float(output_size_bytes) / total_elapsed) / 1024.0 if output_size_bytes > 0 else 0.0
        )

        report = dict(snap)
        report["start_ts"] = self.start_ts
        report["first_data_ts"] = 0.0 if self.first_data_ts is None else self.first_data_ts
        report["last_data_ts"] = 0.0 if self.last_data_ts is None else self.last_data_ts
        report["done_ts"] = self.done_ts
        report["end_to_end_kibps"] = end_to_end_kibps
        report["output_size_bytes"] = float(output_size_bytes)
        # Backward compatibility aliases (deprecated).
        report["goodput_kbps"] = report["goodput_kibps"]
        report["end_to_end_kbps"] = report["end_to_end_kibps"]

        # Cast bools/ints to numeric for backward-compatible numeric dict typing.
        report["manual_roi_applied"] = 1.0 if self.manual_roi_applied else 0.0
        report["auto_to_manual_switches"] = float(self.auto_to_manual_switches)
        report["manual_select_attempts"] = float(self.manual_select_attempts)
        return report
