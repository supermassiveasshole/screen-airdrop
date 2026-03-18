"""Pipeline 抽象基类。

定义所有 pipeline 实现必须遵循的统一接口。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

# New architecture imports
from screen_airdrop.receiver.reporting import (
    AssemblerCollector,
    ReportCollector,
    StatsCollector,
    make_protocol_collector,
)


class BasePipeline(ABC):
    """Pipeline 抽象基类，定义统一接口。

    所有 pipeline 实现（ScreenLiveRuntime, AsyncioPipeline）都应该实现此接口。
    这个接口确保不同的 pipeline 实现可以互换使用。

    Pipeline 在初始化时创建 protocol 特定的 Report 对象，
    在运行过程中由 decoder 直接更新 report。
    """

    def __init__(self, protocol: str):
        """Initialize pipeline with protocol.

        Args:
            protocol: Protocol name (basic, compact, gray4, layered)
        """
        self.protocol = protocol

        # New architecture: report_collector will be set by subclass
        self.report_collector: Optional[ReportCollector] = None

    def _create_report_collector(
        self,
        *,
        stats,
        assembler,
    ) -> ReportCollector:
        """Create report collector for new architecture.

        This method creates a ReportCollector with appropriate collectors
        based on the protocol.

        Args:
            stats: TransferStats or ScreenLiveRuntimeStats instance
            assembler: ChunkAssembler instance

        Returns:
            ReportCollector instance
        """
        # Create stats collector
        stats_collector = StatsCollector(stats)

        # Create protocol collector (None for basic/compact)
        protocol_collector = make_protocol_collector(self.protocol)

        # Create assembler collector
        assembler_collector = AssemblerCollector(assembler)

        # Create report collector
        return ReportCollector(
            stats_collector=stats_collector,
            protocol_collector=protocol_collector,
            assembler_collector=assembler_collector,
        )

    def get_report_collector(self) -> Optional[ReportCollector]:
        """Get the report collector.

        Returns:
            ReportCollector instance or None if not initialized
        """
        return self.report_collector

    @abstractmethod
    def start(self) -> None:
        """启动 pipeline，开始处理帧。

        此方法应该启动所有必要的工作进程/线程，但不应该阻塞。
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """发送停止信号给 pipeline。

        此方法应该发送停止信号，但不应该等待清理完成。
        使用 join() 来等待清理。
        """
        pass

    @abstractmethod
    def wait(self, timeout: Optional[float] = None) -> bool:
        """等待 pipeline 完成。

        Args:
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            True 如果完成，False 如果超时
        """
        pass

    @abstractmethod
    def join(self, timeout: float = 10.0) -> None:
        """停止并清理 pipeline 资源。

        此方法应该等待所有工作进程/线程结束并清理资源。

        Args:
            timeout: 等待超时时间（秒）
        """
        pass

    @abstractmethod
    def check_errors(self) -> None:
        """检查并抛出 pipeline 错误。

        如果 pipeline 遇到错误，此方法应该抛出该错误。

        Raises:
            Exception: 如果 pipeline 遇到错误
        """
        pass

    @abstractmethod
    def snapshot(self) -> Dict[str, Any]:
        """获取 pipeline 统计快照。

        Returns:
            统一格式的统计字典，必须包含：
            - captured: 捕获的帧数
            - decode_ok: 解码成功的帧数
            - decode_fail: 解码失败的帧数
            - assembled: 组装的块数
            - assembled_bytes: 组装的字节数
            以及其他 pipeline 特定的指标
        """
        pass

    # Note: done_event 不是抽象方法，因为它可以是实例变量或 property
    # 子类应该提供 done_event 属性（threading.Event）
