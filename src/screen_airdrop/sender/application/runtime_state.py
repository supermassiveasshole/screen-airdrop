"""Sender runtime state and progress reporting helpers."""

from __future__ import annotations

import time


class SenderRuntimeState:
    def __init__(
        self,
        *,
        protocol,
        session_id,
        payload_size,
        payload_chunk_count,
        frame_payload_cap,
        effective_chunk_size,
        fps,
        stats_interval,
        control_summary,
        data_realizations,
    ):
        self.protocol = protocol
        self.session_id = int(session_id)
        self.payload_size = int(payload_size)
        self.payload_chunk_count = int(payload_chunk_count)
        self.frame_payload_cap = int(frame_payload_cap)
        self.effective_chunk_size = int(effective_chunk_size)
        self.fps = int(fps)
        self.stats_interval = max(0.1, float(stats_interval))
        self.control_summary = control_summary
        self.data_realizations = int(data_realizations)

        self.theoretical_payload_kibps = (
            float(self.effective_chunk_size * max(1, self.fps)) / 1024.0
        )
        self.started = time.time()
        self.sent_frames = 0
        self.sent_data_frames = 0
        self.last_stats_ts = self.started
        self.last_stats_sent_frames = 0
        self.last_stats_sent_data_frames = 0
        self.next_stats_ts = self.started + self.stats_interval

    def print_session_summary(self):
        print(
            "protocol={0} session_id={1} payload_size={2} total_chunks={3} frame_payload_cap={4} theoretical_payload_KiBps={5:.2f}".format(
                self.protocol,
                self.session_id,
                self.payload_size,
                self.payload_chunk_count,
                self.frame_payload_cap,
                self.theoretical_payload_kibps,
            )
        )

    def maybe_print_realtime_stats(self, now):
        if now < self.next_stats_ts:
            return
        elapsed = max(1e-6, now - self.last_stats_ts)
        delta_sent_frames = max(0, self.sent_frames - self.last_stats_sent_frames)
        delta_sent_data_frames = max(
            0, self.sent_data_frames - self.last_stats_sent_data_frames
        )
        tx_fps = float(delta_sent_frames) / elapsed
        data_fps = float(delta_sent_data_frames) / elapsed
        tx_payload_kibps = (
            float(delta_sent_data_frames * self.effective_chunk_size) / elapsed
        ) / 1024.0
        print(
            "sender realtime: sent={0} data={1} tx_fps={2:.2f} data_fps={3:.2f} tx_payload_KiBps={4:.2f} control=[{5}] realizations={6}".format(
                self.sent_frames,
                self.sent_data_frames,
                tx_fps,
                data_fps,
                tx_payload_kibps,
                self.control_summary,
                self.data_realizations,
            )
        )
        self.last_stats_ts = now
        self.last_stats_sent_frames = self.sent_frames
        self.last_stats_sent_data_frames = self.sent_data_frames
        self.next_stats_ts = now + self.stats_interval

    def record_item(self, item):
        self.sent_frames += 1
        if item["kind"] == "data":
            self.sent_data_frames += 1
        self.maybe_print_realtime_stats(time.time())

    def finish(self):
        elapsed = max(0.001, time.time() - self.started)
        observed_payload_kibps = (
            float(self.sent_data_frames * self.effective_chunk_size) / elapsed / 1024.0
        )
        print(
            "sender finished: sent_frames={0} sent_data_frames={1} observed_payload_KiBps={2:.2f}".format(
                self.sent_frames,
                self.sent_data_frames,
                observed_payload_kibps,
            )
        )
        return elapsed, observed_payload_kibps
