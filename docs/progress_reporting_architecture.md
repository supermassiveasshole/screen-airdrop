# Progress Reporting Architecture

## 概述

这套进度报告系统遵循 SOLID 原则，提供可扩展的架构来支持不同的输出方式（命令行、GUI、日志文件等）和不同的 pipeline 类型。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                      PipelineRunner                          │
│  (运行循环，超时检查，委托进度报告)                           │
└────────────────────┬────────────────────────────────────────┘
                     │ 依赖抽象
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              ProgressReporter (抽象接口)                      │
│  - report_progress(snapshot, missing, elapsed)               │
│  - report_completion(status, path, size)                     │
│  - report_error(error)                                       │
└────────────────────┬────────────────────────────────────────┘
                     │ 实现
         ┌───────────┼───────────┐
         ▼           ▼           ▼
┌─────────────┐ ┌─────────┐ ┌──────────────┐
│  Console    │ │   GUI   │ │   Silent     │
│  Reporter   │ │ Reporter│ │  Reporter    │
└──────┬──────┘ └─────────┘ └──────────────┘
       │ 使用
       ▼
┌─────────────────────────────────────────────────────────────┐
│              StatsFormatter (抽象接口)                        │
│  - format_progress_line(snapshot, missing, delta)            │
└────────────────────┬────────────────────────────────────────┘
                     │ 实现
         ┌───────────┼───────────┐
         ▼           ▼           ▼
┌─────────────┐ ┌─────────┐ ┌──────────────┐
│ ScreenLive  │ │ Replay  │ │   Compact    │
│ Formatter   │ │Formatter│ │  Formatter   │
└─────────────┘ └─────────┘ └──────────────┘
```

## SOLID 原则体现

### 1. Single Responsibility Principle (单一职责)

- **PipelineRunner**: 只负责运行循环和超时检查
- **ProgressReporter**: 只负责输出进度信息
- **StatsFormatter**: 只负责格式化统计数据
- **Pipeline**: 只负责数据处理

### 2. Open/Closed Principle (开闭原则)

- 添加新的输出方式：实现 `ProgressReporter` 接口
- 添加新的 pipeline 类型：实现 `StatsFormatter` 接口
- 无需修改现有代码

### 3. Liskov Substitution Principle (里氏替换)

- 所有 `ProgressReporter` 实现可以互换使用
- 所有 `StatsFormatter` 实现可以互换使用

### 4. Interface Segregation Principle (接口隔离)

- `ProgressReporter` 接口简洁，只有 3 个方法
- `StatsFormatter` 接口只有 1 个方法
- 实现者不需要实现不需要的方法

### 5. Dependency Inversion Principle (依赖倒置)

- `PipelineRunner` 依赖 `ProgressReporter` 抽象，不依赖具体实现
- `ConsoleProgressReporter` 依赖 `StatsFormatter` 抽象

## 使用示例

### 1. 命令行模式（当前实现）

```python
from screen_airdrop.receiver.runtime.console_reporter import ConsoleProgressReporter
from screen_airdrop.receiver.runtime.stats_formatter import ScreenLiveStatsFormatter

# 创建格式化器和报告器
formatter = ScreenLiveStatsFormatter()
reporter = ConsoleProgressReporter(formatter)

# 创建 runner
runner = PipelineRunner(
    pipeline=pipeline,
    assembler=assembler,
    progress_reporter=reporter,
    # ... 其他参数
)
```

### 2. GUI 模式（未来）

```python
from my_app.gui_reporter import GUIProgressReporter

# 创建 GUI 报告器
reporter = GUIProgressReporter(progress_bar_widget, status_label_widget)

# 创建 runner（相同的接口）
runner = PipelineRunner(
    pipeline=pipeline,
    assembler=assembler,
    progress_reporter=reporter,
    # ... 其他参数
)
```

### 3. 静默模式（测试）

```python
from screen_airdrop.receiver.runtime.progress_reporter import SilentProgressReporter

# 创建静默报告器
reporter = SilentProgressReporter()

# 创建 runner
runner = PipelineRunner(
    pipeline=pipeline,
    assembler=assembler,
    progress_reporter=reporter,
    # ... 其他参数
)
```

### 4. 添加新的 Pipeline 类型

```python
from screen_airdrop.receiver.runtime.stats_formatter import StatsFormatter

class MyCustomFormatter(StatsFormatter):
    def format_progress_line(self, snapshot, missing_count, delta_snapshot, delta_seconds):
        # 提取自定义指标
        my_metric = snapshot.get("my_custom_metric", 0)

        # 格式化输出
        return f"custom_metric={my_metric} ..."

# 使用自定义格式化器
formatter = MyCustomFormatter()
reporter = ConsoleProgressReporter(formatter)
```

## 输出格式

### ScreenLiveStatsFormatter 输出

完整的性能指标（22 个字段）：

```
captured=124 decoded=43 assembled=41 missing=267 dropped=0/0 dedup=79
cap_fps=41.78 raw_grab_fps=40.56 prep_fps=40.56 accepted_fps=14.72
dec_fps=19.90 prep_backlog=0 overwrite=0 decode_q=2 rx_KBps=146.20
grab_ms=12.89 copy_ms=0.00 ipc_recv_ms=0.00 dedup_ms=0.00
fp_ms=0.07 mat_ms=0.00 dump_ms=0.00
```

### CompactStatsFormatter 输出

简化的进度信息（4 个字段）：

```
captured=124 decode_ok=43 decode_fail=2 missing=267
```

## 扩展点

### 1. 添加新的输出方式

实现 `ProgressReporter` 接口：

- `report_progress()`: 实时进度更新
- `report_completion()`: 完成状态
- `report_error()`: 错误信息

### 2. 添加新的格式化器

实现 `StatsFormatter` 接口：

- `format_progress_line()`: 从 snapshot 提取和格式化数据

### 3. 添加新的指标

1. 在 Pipeline 的 `snapshot()` 方法中添加新指标
2. 在对应的 `StatsFormatter` 中提取和格式化新指标
3. 无需修改其他代码

## 测试策略

### 1. 单元测试

```python
def test_screen_live_formatter():
    formatter = ScreenLiveStatsFormatter()
    snapshot = {"captured": 100, "decode_ok": 50, ...}
    line = formatter.format_progress_line(snapshot, missing_count=10)
    assert "captured=100" in line
    assert "decoded=50" in line
```

### 2. 集成测试

```python
def test_console_reporter_with_formatter():
    formatter = ScreenLiveStatsFormatter()
    reporter = ConsoleProgressReporter(formatter)

    # 捕获 stdout
    with captured_output() as output:
        reporter.report_progress(snapshot, missing_count=10, elapsed_seconds=5.0)

    assert "captured=" in output.getvalue()
```

## 性能考虑

1. **格式化开销**: 每秒调用一次，开销可忽略
2. **Delta 计算**: 只在需要时计算增量，避免不必要的计算
3. **内存占用**: 只保留上一次 snapshot，内存占用 < 1KB

## 未来扩展

1. **日志文件输出**: 实现 `FileProgressReporter`
2. **网络监控**: 实现 `NetworkProgressReporter` (WebSocket/HTTP)
3. **多语言支持**: 在 `StatsFormatter` 中添加 i18n
4. **自定义主题**: 在 `ConsoleProgressReporter` 中添加颜色支持
5. **进度条**: 在 `ConsoleProgressReporter` 中添加 tqdm 集成
