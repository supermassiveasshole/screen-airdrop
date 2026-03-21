"""Pipeline 运行器，封装运行循环和报告生成。"""

import time
from typing import Optional, Tuple

from screen_airdrop.receiver.assembler import ChunkAssembler
from screen_airdrop.receiver.reporting.report import Report
from screen_airdrop.receiver.restore import restore_payload
from screen_airdrop.receiver.runtime.base_pipeline import BasePipeline
from screen_airdrop.receiver.runtime.progress_reporter import ProgressReporter


class PipelineRunner:
    """Pipeline 运行器，封装运行循环和报告生成。

    职责：
    - 启动和监控 pipeline
    - 检查超时条件
    - 委托进度报告给 ProgressReporter
    - 生成最终报告
    - 处理文件恢复
    """

    def __init__(
        self,
        pipeline: BasePipeline,
        assembler: ChunkAssembler,
        max_seconds: int,
        max_idle_seconds: int,
        stats_interval: float,
        output_dir: str = ".",
        progress_reporter: Optional[ProgressReporter] = None,
    ):
        """初始化 PipelineRunner。

        Args:
            pipeline: Pipeline 实例（实现 BasePipeline 接口）
            assembler: ChunkAssembler 实例
            max_seconds: 最大运行时间（秒），0 表示无限制
            max_idle_seconds: 最大空闲时间（秒）
            stats_interval: 统计打印间隔（秒）
            output_dir: 输出目录（默认为当前目录）
            progress_reporter: 进度报告器（None 表示不报告进度）
        """
        self.pipeline = pipeline
        self.assembler = assembler
        self.max_seconds = max_seconds
        self.max_idle_seconds = max_idle_seconds
        self.stats_interval = stats_interval
        self.output_dir = output_dir
        self.progress_reporter = progress_reporter

        self.start_time = time.time()
        self.last_good_time = self.start_time
        self.next_stats_time = self.start_time + stats_interval
        self._last_decode_ok = 0
        self._last_assembled = 0

    def run(self) -> Tuple[int, Report]:
        """运行 pipeline 直到完成或超时。

        Returns:
            (exit_code, report) 元组
            - exit_code: 0=成功, 1=中断, 2=超时
            - report: Report 对象
        """
        self.pipeline.start()

        try:
            return self._run_loop()
        except KeyboardInterrupt:
            report = self._build_report(status="aborted", output_size_bytes=0, output_path="")
            return (1, report)
        finally:
            self.pipeline.stop()
            self.pipeline.join()

    def _run_loop(self) -> Tuple[int, Report]:
        """主监控循环。"""
        while not self.assembler.complete():
            now = time.time()

            # 检查错误
            self.pipeline.check_errors()

            # 检查超时
            timeout_result = self._check_timeouts(now)
            if timeout_result is not None:
                return timeout_result

            # 打印进度
            if now >= self.next_stats_time:
                self._print_stats()
                self.next_stats_time = now + self.stats_interval

            snap = self.pipeline.snapshot()
            self._refresh_last_good_time(snap, now)

            time.sleep(0.1)

        # 成功完成
        return self._handle_success()

    def _check_timeouts(self, now: float) -> Optional[Tuple[int, Report]]:
        """检查超时条件。

        Args:
            now: 当前时间戳

        Returns:
            如果超时，返回 (exit_code, report)；否则返回 None
        """
        if self.max_seconds > 0 and now - self.start_time > self.max_seconds:
            report = self._build_report(
                status="timeout_max_seconds", output_size_bytes=0, output_path=""
            )
            if self.progress_reporter:
                self.progress_reporter.report_completion(
                    status="timeout_max_seconds",
                    output_path="",
                    output_size_bytes=0,
                )
            return (2, report)

        if now - self.last_good_time > self.max_idle_seconds:
            report = self._build_report(status="timeout_idle", output_size_bytes=0, output_path="")
            if self.progress_reporter:
                self.progress_reporter.report_completion(
                    status="timeout_idle",
                    output_path="",
                    output_size_bytes=0,
                )
            return (2, report)

        return None

    def _refresh_last_good_time(self, snapshot: dict, now: float) -> None:
        """Refresh idle timer only when decode/assembly counters advance."""
        decode_ok = int(snapshot.get("decode_ok", 0) or 0)
        assembled = int(snapshot.get("assembled", 0) or 0)

        if decode_ok > self._last_decode_ok or assembled > self._last_assembled:
            self.last_good_time = now

        self._last_decode_ok = decode_ok
        self._last_assembled = assembled

    def _print_stats(self) -> None:
        """打印实时统计（委托给 ProgressReporter）。"""
        if self.progress_reporter is None:
            return

        snap = self.pipeline.snapshot()
        missing = self.assembler.missing_count()
        elapsed = time.time() - self.start_time

        self.progress_reporter.report_progress(
            snapshot=snap,
            missing_count=missing,
            elapsed_seconds=elapsed,
        )

    def _handle_success(self) -> Tuple[int, Report]:
        """处理成功完成。

        Returns:
            (exit_code, report) 元组
        """
        payload_bytes = self.assembler.payload()
        output_size = len(payload_bytes)

        # 恢复文件
        output_path = ""
        if self.assembler.manifest is not None:
            output_path = restore_payload(
                payload_bytes,
                self.assembler.manifest,
                self.output_dir,
            )

        report = self._build_report(
            status="ok",
            output_size_bytes=output_size,
            output_path=output_path,
        )

        if self.progress_reporter:
            self.progress_reporter.report_completion(
                status="ok",
                output_path=output_path,
                output_size_bytes=output_size,
            )

        return (0, report)

    def _build_report(
        self,
        status: str,
        output_size_bytes: int,
        output_path: str = "",
    ) -> Report:
        """构建最终报告。

        Args:
            status: 报告状态
            output_size_bytes: 输出大小（字节）
            output_path: 输出文件路径

        Returns:
            Report 对象
        """
        # Get pipeline-specific stats snapshot
        pipeline_snap = self.pipeline.snapshot()

        # Generate report using new architecture
        report_collector = self.pipeline.get_report_collector()
        if report_collector is None:
            raise RuntimeError("Pipeline does not have report_collector")

        report = report_collector.finalize(
            status=status,
            output_size_bytes=output_size_bytes,
            output_path=output_path,
            ts=time.time(),
            pipeline_snap=pipeline_snap,
        )

        return report
