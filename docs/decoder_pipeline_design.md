# Decoder Pipeline Design

本文档描述当前 `screen-airdrop` receiver 端 live decoder pipeline 的完整设计。目标不是“介绍大概思路”，而是把当前实现背后的约束、哲学、状态机、进程模型、事件协议和运行顺序讲清楚，使你可以据此从零复现出一套等价 pipeline。

本文档描述的实现对应当前仓库中的 live screen runtime，核心入口和实现分散在以下文件：

- [src/screen_airdrop/receiver/cli.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/cli.py)
- [src/screen_airdrop/receiver/application/pipeline_factory.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/application/pipeline_factory.py)
- [src/screen_airdrop/receiver/pipeline/live.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/pipeline/live.py)
- [src/screen_airdrop/receiver/runtime/coordinator.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/coordinator.py)
- [src/screen_airdrop/receiver/runtime/workers.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/workers.py)
- [src/screen_airdrop/receiver/runtime/slot_manager.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/slot_manager.py)
- [src/screen_airdrop/receiver/runtime/prep_strategy.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/prep_strategy.py)
- [src/screen_airdrop/receiver/runtime/geometry_tracker.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/geometry_tracker.py)
- [src/screen_airdrop/receiver/runtime/stats.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/stats.py)
- [src/screen_airdrop/receiver/pipeline/runner.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/pipeline/runner.py)

## 1. 设计目标

这套 pipeline 不是一个“尽量多线程并行”的通用视频处理框架，而是一个围绕以下约束设计的定制 runtime。

### 1.1 目标

1. 在本机抓取远端窗口或指定 ROI 中的画面。
2. 尽快把一帧送入解码链路。
3. 尽量复用上一次几何状态，避免每帧全图定位。
4. 对重复帧做极早期去重，减少无意义 decode。
5. 把 decode 和 assemble 分开，让“抓帧”和“拼文件”解耦。
6. 在 Ctrl+C、timeout、worker 崩溃时可以回收进程和共享内存。

### 1.2 非目标

1. 不追求每一帧都被 decode。
2. 不保证抓帧速率和 decode 速率相同。
3. 不追求绝对实时，而追求对 burst、长尾、重复帧、偶发抓屏抖动的鲁棒性。

### 1.3 layered vNext 现状

当前仓库里的 `layered` 已进入 vNext transport 版本：

1. bootstrap 被压缩为最小 body-decode 入口层，只保留短会话标签、frame type、body profile、payload_len 和 mask。
2. `epoch_id/frame_id` 不再占用 bootstrap 强保护空间，而是移到 body metadata。
3. body 现在有两个显式 profile：
   - `dense`
   - `robust`
4. sender 默认根据 `ecc_level` 选择 body profile：
   - `L/M -> dense`
   - `Q/H -> robust`
5. vNext.1 进一步把 bootstrap control band 改成了独立的 `2-bit template cell`：
   - 每个 `3x2` control cell 承载 1 个 dibit
   - bootstrap band 现在是 `4` 行 control + `1` 行 isolation
   - receiver 通过 reference templates 做 per-cell 模板匹配，而不是单阈值二值化
6. live runtime 不关心 body profile 的调度，只负责把 frame 送到协议 decoder；profile 选择完全属于 transport 层。
7. layered v6 的 `session_id` 语义已经收敛为 on-wire 的 16-bit session identity：
   - sender 在 layered 路径上会先把 session id 归一化到 16-bit
   - bootstrap 里的 `short_session_tag` 就是 layered transport 的真实 session identity
   - receiver/reporting 不再把它视为某个更长 session id 的临时截断别名
8. live runtime 的 worker 边界必须保留 layered 成功元数据：
   - `body_profile_id`
   - `body_profile_name`
   否则 replay 看得到的 observability，screen-live report 会丢失。

## 2. 核心哲学

### 2.1 抓帧优先

这套 pipeline 的第一原则是：`grab` 是整个系统的节拍器。

如果发送端正在高速播放，而接收端把大量时间花在 decode、assemble、报告、debug 输出上，最终结果不是“更聪明”，而是“错过帧”。因此实现上始终假设：

1. `grab` 应当尽量稳定地跑在目标 FPS 附近。
2. `decode` 可以落后，可以堆积一点 queue。
3. 重复帧要在 decode 前尽可能早地丢掉。

### 2.2 固定 slot，而不是无界 frame queue

live runtime 使用的是固定数量共享内存 slot，而不是一个不断增长的 frame 队列。

原因：

1. 屏幕帧尺寸固定，使用共享内存 slot 可以避免大对象跨进程复制。
2. slot 可以携带 generation，天然支持陈旧帧检测。
3. slot 生命周期明确，便于回收、重用、统计和 backpressure。

### 2.3 generation 比 “最新覆盖” 更重要

slot 的正确性依赖 generation，而不是 slot_id 本身。

同一个 slot_id 会被不断重用。如果没有 generation：

1. decode worker 可能在处理已经被 grab 覆写的新帧。
2. coordinator 无法判断某个 descriptor 是否陈旧。
3. dump/prep/decode 完成后会释放错的 slot。

因此 slot 生命周期的核心不是 “这个 slot 有没有被占用”，而是：

`slot_id + generation` 是否仍然是当前版本。

### 2.4 去重越早越好

重复帧非常常见，特别是在 sender 显示静止内容、控制帧或文件传输尾部阶段。设计上把 fingerprint + duplicate 判定放在 decode 之前，是因为：

1. fingerprint 远比完整 decode 便宜。
2. 重复帧对 assembler 没有新信息。
3. 提前丢重复帧可以显著降低 decode 进程数带来的系统调度干扰。

### 2.5 geometry lock 是第二节拍器

抓帧决定时间节拍，geometry lock 决定空间节拍。

receiver 不想每帧都重新定位 finder patterns，因此引入两态几何状态机：

1. `acquire`
   全量定位，建立 homography。
2. `locked`
   用已有 geometry 快速 decode。

失败次数超过阈值后，回退到 `acquire` 重新定位。

## 3. 顶层架构

live screen receiver 由四层组成：

1. CLI 和 config 层
2. runtime orchestration 层
3. worker/coordinator 层
4. assembler/restore/report 层

### 3.1 启动链路

启动顺序：

1. CLI 解析参数并构造 `ReceiverConfig`
2. ROI 通过 `setup_roi(...)` 决定
3. `pipeline_factory.create_pipeline(...)` 决定创建 replay pipeline 还是 live runtime
4. screen source 下创建 `ScreenLiveRuntime`
5. `PipelineRunner.run()` 启动 runtime，并负责 timeout / stats / final report

代码入口：

- CLI: [src/screen_airdrop/receiver/cli.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/cli.py)
- Factory: [src/screen_airdrop/receiver/application/pipeline_factory.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/application/pipeline_factory.py)
- Runner: [src/screen_airdrop/receiver/pipeline/runner.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/pipeline/runner.py)

## 4. 进程与线程模型

### 4.1 真实运行时结构

当前 live runtime 包含：

1. 主进程
   持有 CLI、`PipelineRunner`、`ScreenLiveRuntime`、assembler、stats。
2. coordinator 线程
   在主进程内运行 asyncio event loop。
3. 1 个 grab 子进程
4. 0 或 1 个 prep 子进程
5. N 个 decode 子进程
6. 可选 1 个 dump 子进程

### 4.2 为什么 coordinator 在线程里

`ScreenLiveRuntime.start()` 启动 worker 子进程后，不在主线程直接跑 coordinator，而是起一个非 daemon 线程：

- [src/screen_airdrop/receiver/pipeline/live.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/pipeline/live.py)

这样做的原因：

1. 主线程仍可被 `PipelineRunner` 用于 timeout、stats、错误检查。
2. Ctrl+C 可以先打到主线程，再由 stop/shutdown 协调整个 runtime 收尾。
3. coordinator 自己可以用 `asyncio.run(...)` 拥有独立 event loop。

### 4.3 为什么 worker 用 subprocess

grab、decode、prep、dump 都放到 subprocess，核心原因是：

1. 避开 GIL 对高频抓帧和 decode 的干扰。
2. 用共享内存传帧，用 queue 传 descriptor，比把大 ndarray 直接跨进程传递更便宜。
3. 崩一个 worker 时可单独上报、终止和回收。

## 5. ROI 与 capture region

### 5.1 两种 ROI

pipeline 里有两个不同概念的 ROI：

1. `capture region`
   真正交给 `mss.grab()` 的区域。
2. `initial_search_roi` / tracking ROI
   解码阶段 locator 的搜索范围。

这两个不能混为一谈。

### 5.2 capture region 的来源

当前 CLI 会把最终选定的 `region` 直接传进 `ScreenCapture`：

- [src/screen_airdrop/receiver/cli.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/cli.py)

runtime 初始化时又会用：

1. `capture.window_title`
2. `capture.region`
3. `monitor_region`

经过 `resolve_window_region(...)` 得到最终 active region：

- [src/screen_airdrop/receiver/pipeline/live.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/pipeline/live.py)

### 5.3 pipeline seed ROI 的来源

`pipeline_factory._build_pipeline_seed_roi_local(...)` 会把绝对屏幕坐标的 forced ROI 转换到局部 frame 坐标，作为 locator 的初始搜索区域：

- [src/screen_airdrop/receiver/application/pipeline_factory.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/application/pipeline_factory.py)

这意味着：

1. 抓帧区域可以是一个裁剪后的局部屏幕。
2. 在这个局部帧内部，locator 仍然可以进一步只在更小的 seed ROI 内搜索。

## 6. 共享内存与 slot 设计

### 6.1 为什么用共享内存

抓屏得到的是一张固定尺寸的 BGRA 图像。最自然的高性能传递方式是：

1. 预先申请固定大小共享内存
2. grab 把像素写进 slot
3. 后续 worker 只拿 descriptor 读取 slot

这样避免：

1. 每帧创建新的大 ndarray
2. 每帧在进程间 pickle 整块图像

### 6.2 slot 数量

slot 数量不是固定常数，而是基于 capture_fps、decode_workers、dump 是否开启计算：

- [src/screen_airdrop/receiver/pipeline/live.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/pipeline/live.py)

当前逻辑：

1. `base_slots = 4`
2. `fps_based_slots = capture_fps * 2` if FPS > 10
3. `decode_based_slots = decode_workers * 3 + 6`
4. 取最大值，再在 dump 开启时额外加 1

设计哲学：

1. 低 FPS 时，少量 slot 就够。
2. 高 FPS 时，需要额外缓冲 absorb burst。
3. decode worker 增多时，slot 也要增多，否则 grab 容易 starvation。

### 6.3 slot 数据格式

当前 slot 使用 RGBA 四通道：

- [src/screen_airdrop/receiver/runtime/workers.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/workers.py)

原因：

1. MSS 天生输出 BGRA。
2. 直接复制 4 通道，比 RGB slice copy 便宜。
3. decode 侧读取时再做 `[:, :, :3]` 的 view，不需要额外复制。

### 6.4 SlotManager 状态机

`SlotManager` 定义 slot 的生命周期：

- `FREE`
- `FILLING`
- `FILLED`
- `IN_DECODE`
- `RECLAIMING`

核心操作：

1. `allocate_for_grab(writer_owner)`
   从 free list 取 slot，generation + 1，状态变成 `FILLING`
2. `mark_filled(descriptor, writer_owner)`
   grab 完成后标记为 `FILLED`
3. `assign_decode(descriptor, worker_id)`
   coordinator 派给 decode worker，状态进入 `IN_DECODE`
4. `complete_decode(descriptor, worker_id)`
   decode 完成后释放
5. `mark_duplicate_and_release(descriptor)`
   duplicate 直接释放

实现：

- [src/screen_airdrop/receiver/runtime/slot_manager.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/slot_manager.py)

### 6.5 generation 的作用

每次 `allocate_for_grab(...)` 时都会做：

`slot.generation += 1`

之后所有 descriptor 都必须带这个 generation。后续任一阶段只要发现 generation 不匹配，就说明：

1. 这个 descriptor 已经过时
2. slot 已经被重用
3. 当前结果必须丢弃

这就是为什么 system 允许：

1. grab 很快地重复使用同一个 slot_id
2. 而不会把旧 decode 结果错误地释放到新帧上

## 7. 事件协议

worker 与 coordinator 之间传递的不是图像，而是小对象事件。

定义见：

- [src/screen_airdrop/receiver/runtime/events.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/events.py)

核心事件：

1. `FilledSlotEvent`
   grab 已把一帧写进 slot
2. `PreparedSlotEvent`
   fingerprint 完成，且不是 duplicate
3. `DuplicateSlotEvent`
   fingerprint 完成，判断为 duplicate
4. `PrepFingerprintEvent`
   prep 子进程模式下的原始 fingerprint 结果
5. `DecodeAssignment`
   coordinator 派给某个 decode worker 的任务
6. `DecodeCompletion`
   decode worker 返回的成功/失败结果
7. `DumpCopyCompletion`
   dump worker 完成复制

还有一些轻量 dict 事件：

1. `{"kind": "grab_slot_starvation"}`
2. `{"kind": "raw_grab_stats", "grab_ms": ...}`
3. `{"kind": "slot_wait_ms", "value": ...}`
4. `{"kind": "error", "stage": ..., "error": ...}`

## 8. grab 设计

### 8.1 设计原则

grab 子进程的职责很窄：

1. 等待 deadline
2. 取一个可写 slot
3. 调 `mss.grab()`
4. 把图像写入共享内存
5. 发 `FilledSlotEvent`

它不负责：

1. decode
2. geometry
3. assemble
4. duplicate 判定

### 8.2 为什么有 slot bridge 线程

跨进程 queue 的 `get()` 是阻塞的。如果在 grab 的 event loop 里直接调用：

1. event loop 会被卡住
2. 之前提交出去的 async copy 也可能饿死

所以当前实现使用一个很小的 bridge：

1. `slot_bridge` 线程阻塞读取 `slot_assign_queue`
2. 把结果转发到本地 `queue.Queue`
3. event loop 只做 `get_nowait()`

实现：

- [src/screen_airdrop/receiver/runtime/workers.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/workers.py)

### 8.3 当前 copy 设计

当前实现已经不再使用早期实验过的：

1. `asyncio.create_task(...) + asyncio.to_thread(...)`
2. 通用 `ThreadPoolExecutor`
3. memoryview Python 循环 copy

原因不是这些方案“完全不能工作”，而是它们在真实传输时都暴露过同一个问题：**copy 的真实 memcpy 很快，但 completion 调度会抖动，最后反向污染 grab 的稳定性**。

当前最终保留的是固定 copy worker 线程：

1. `grab` 调完 `mss.grab()` 后把 `(shot_raw, slot_id, generation, ...)` 放入有界 `copy_queue`
2. 2 个固定 copy worker 线程执行 `_rgba_zero_copy(...)`
3. copy 完后发 `FilledSlotEvent`
4. 如果 `copy_queue` 满，当前 grab 路径会退化为 inline copy，而不是静默积压

相关常量：

- `_COPY_WORKERS = 2`
- `_COPY_QUEUE_DEPTH = 8`

实现：

- [src/screen_airdrop/receiver/runtime/workers.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/workers.py)

### 8.4 为什么最终是“固定 copy worker”，而不是别的方案

从当前实现和历史实验看，几个候选方案的取舍是：

1. 不把 copy 放到 prep
   prep 的输入已经是 `FilledSlotEvent`，而不是原始 `shot_raw`。如果把 copy 下放到 prep，会破坏 slot 的填充时序和 ownership 语义。
2. 不再使用 `asyncio.to_thread`
   它会把 copy completion 的调度抖动留在 grab 子进程内部。真实实测里，`copy_exec_ms` 很低，但 `copy_wait_ms` 可以涨到几十毫秒。
3. 不额外开 copy subprocess
   这会引入新的大对象传递、更多 IPC、以及更复杂的 shutdown/resource tracking 问题，而当前问题并没有大到必须付出这个复杂度。
4. 选择固定小线程池
   这是当前最小、可控、且与 grab 热路径耦合最低的方案。grab 只负责 enqueue，copy 的等待和完成路径从 event loop 中剥离。

### 8.5 grab 指标

当前 runtime 专门区分：

1. `grab_ms`
   `mss.grab()` 的 wall time
2. `cpu_grab_ms`
   同一段期间当前线程真正消耗的 CPU 时间
3. `copy_ms`
   copy 完成总耗时
4. `copy_exec_ms`
   真正 memcpy 耗时
5. `copy_wait_ms`
   调度/排队等待耗时

这样可以区分：

1. 是系统抓屏本身慢
2. 还是 Python/调度在慢

## 9. prep 设计

### 9.1 prep 的职责

prep 只做两件事：

1. 在一个较小 ROI 上计算 fingerprint
2. 和上一帧 fingerprint 比较，决定是不是 duplicate

它不做 decode。

### 9.2 prep ROI

prep 只取较小 ROI，而不是全帧。理由：

1. fingerprint 需要快
2. duplicate 判定只是早期粗筛，不需要全图信息
3. 中央区域通常更稳定，能减少边缘噪声

### 9.3 两种 prep 模式

实现有两种：

1. `AsyncPrepStrategy`
   coordinator event loop 内做 fingerprint
2. `ProcessPrepStrategy`
   独立 prep 子进程做 fingerprint

实现：

- [src/screen_airdrop/receiver/runtime/prep_strategy.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/prep_strategy.py)

当前配置项：

- `--prep-process 0`
  async prep
- `--prep-process 1`
  process prep

### 9.4 duplicate 阈值

当前 duplicate 判定阈值是：

`dedup_score < 0.015`

命中 duplicate 时，slot 直接释放，不进入 decode。

## 10. decode 设计

### 10.1 decode worker 的输入输出

输入是 `DecodeAssignment`：

1. 指向共享内存 slot 的 descriptor
2. 当前 geometry generation
3. 可能存在的 geometry_state
4. 当前 tracking ROI

输出是 `DecodeCompletion`：

1. 成功时带 frame_id、chunk_id、payload、meta、proposed_geometry_state
2. 失败时带 error、failure_class、context

### 10.2 为什么 decode 用独立进程池

decode 本身是 CPU 重负载，并且会触发较多 numpy/OpenCV 运算。拆到子进程的收益：

1. 避免主进程 event loop 被 decode 压死
2. 避免 grab 的时间稳定性被单解释器 GIL 拖累
3. 可通过 `decode-workers` 线性试探吞吐与系统干扰之间的平衡点

### 10.3 geometry reuse

decode worker 会优先尝试：

1. 若 protocol 为 layered 且 geometry 已锁定
   调 `decode_frame_with_geometry(...)`
2. 否则走普通 `decode_frame(...)`

成功后，worker 可以通过 `geometry_from_meta(...)` 产出新的 `GeometryState` 候选，交回 coordinator 决定是否接受。

## 11. geometry 状态机

`GeometryTracker` 维护两态状态机：

1. `acquire`
   需要重新定位 frame geometry
2. `locked`
   已有可信几何状态，可复用 homography

转换规则：

1. decode 成功且 `decode_quality >= threshold`
   接受几何，进入 `locked`
2. `locked` 状态下连续失败超过阈值
   回退到 `acquire`

实现：

- [src/screen_airdrop/receiver/runtime/geometry_tracker.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/geometry_tracker.py)

这套设计的哲学是：

1. 几何状态是“软状态”，不是强一致状态
2. 成功时尽量锁住，失败时尽快放弃
3. 允许 occasional failure，但不允许长时间错误复用

## 12. coordinator 设计

### 12.1 coordinator 是什么

coordinator 是整个 runtime 的“纯事件路由器”。

它不做抓屏，也不做 decode 算法本身，而是负责：

1. 收 worker 事件
2. 更新 slot 状态
3. 更新 stats
4. 调度 prep
5. 调度 decode
6. 回收 slot
7. 推动 assembler

实现：

- [src/screen_airdrop/receiver/runtime/coordinator.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/coordinator.py)

### 12.2 coordinator 的并发模型

coordinator 不是单 while-loop 顺序读所有 queue，而是并发任务：

1. `_process_grab_events()`
2. `_process_decode_events()`
3. `_process_prep_events_async()` 或 `_process_prep_events_process()`
4. 可选 `_process_dump_events()`

这些任务共享同一个 asyncio event loop，但分别阻塞在不同队列上。

### 12.3 grab 事件处理

收到 `FilledSlotEvent` 后：

1. 调 `slot_manager.mark_filled(...)`
2. 更新 `captured/raw_grab/copy_ms` 等 stats
3. 把事件交给 prep strategy

收到 `grab_slot_starvation` 或 `raw_grab_stats` 时，只更新统计，不改 slot 生命周期。

### 12.4 prep 结果处理

prep 结果分三类：

1. `DuplicateSlotEvent`
   立即释放 slot，重新派发给 grab
2. `PreparedSlotEvent`
   构造 `DecodeAssignment`
3. `PrepFingerprintEvent`
   这是 process prep 模式下的“原始 fingerprint 结果”，coordinator 还要自己做 duplicate 判定

### 12.5 decode 结果处理

成功：

1. 更新 decode 成功统计
2. 提交 geometry proposal
3. 若是数据帧则喂给 assembler
4. 释放 slot 给 grab

失败：

1. 更新 failure class 统计
2. 让 geometry tracker 记录 failure
3. 必要时触发 reacquire
4. 释放 slot 给 grab

## 13. assemble 与 completion

decode worker 只负责把单帧 payload 解出来，不负责组装完整文件。

assembler 在主进程中维护：

1. chunk 去重
2. chunk completion
3. manifest 完整性
4. 最终 payload 重建

一旦 `assembler.complete()` 为真：

1. coordinator 设置 stop_event
2. `PipelineRunner` 跳出主循环
3. `restore_payload(...)` 把最终文件恢复到 output_dir

## 14. stats 设计

`ScreenLiveRuntimeStats` 记录三类数据：

1. 数量
   `captured`, `decode_ok`, `assembled`, `duplicate_frames`
2. 时间
   `capture_grab_time_ms`, `capture_copy_time_ms`, `fingerprint_time_ms`
3. pipeline 状态
   `raw_grab_frames`, `accepted_for_decode_frames`, `decode_queue_depth`, `prep_backlog`

快照生成见：

- [src/screen_airdrop/receiver/runtime/stats.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/runtime/stats.py)

需要注意：

1. `raw_grab_fps`
   统计的是总抓屏次数，包括没有 slot 的情况
2. `cap_fps`
   实际上对应 `captured`
3. `accepted_fps`
   prep 后真正进入 decode 的帧速

因此三者不相等是正常的。

## 15. timeout 与退出设计

### 15.1 两层 stop

有两个 stop 信号：

1. `threading.Event`：主进程/线程侧停止
2. `multiprocessing.Event`：子进程侧停止

`ScreenLiveRuntime.stop()` 会同时设置两者，并广播 queue sentinel。

### 15.2 为什么要广播 sentinel

很多 worker 都可能阻塞在 queue `get()` 上。只设置 stop flag 不够，因为阻塞 `get()` 看不到 flag。

因此 shutdown 时要给这些队列塞 `None`，让 reader 醒来退出：

1. `grab_slot_queue`
2. `grab_event_queue`
3. `prep_input_queue`
4. `prep_output_queue`
5. decode assignment/result queues
6. dump queues

### 15.3 shutdown 顺序

当前 `_shutdown_processes()` 分七个阶段：

1. set stop events
2. 广播 sentinel
3. 等待优雅退出
4. `terminate()` 顽固进程
5. 必要时 `kill()`
6. `join()` / `close()` 所有 process handle
7. 关闭 queue，最后 `close()+unlink()` shared memory

实现：

- [src/screen_airdrop/receiver/pipeline/live.py](/Users/waldron/Code/screen-airdrop/src/screen_airdrop/receiver/pipeline/live.py)

这套顺序的目的不是“优雅”，而是避免：

1. orphan 子进程
2. queue feeder thread 残留
3. shared memory 残留

## 16. 如何从零复现这套 pipeline

如果你要自己实现一个等价系统，最小版本可以按下面顺序搭建。

### 16.1 第一步：固定 slot 共享内存

1. 预先申请 `N` 个共享内存块
2. 每块大小是 `width * height * 4`
3. 给每个 slot 分配：
   - `slot_id`
   - `generation`
   - `state`

### 16.2 第二步：grab worker

grab worker 要做：

1. 基于 `target_fps` 维护 deadline
2. 从 `slot_assign_queue` 取 `(slot_id, generation)`
3. 调 `mss.grab(monitor)`
4. 把 BGRA 写进共享内存
5. 发 `FilledSlotEvent`

重要细节：

1. 不要把跨进程阻塞 `get()` 直接放在 event loop 热路径里
2. 不要每帧把大图像对象跨进程发送
3. 要显式区分 `grab_ms` 和 `copy_ms`

### 16.3 第三步：coordinator

coordinator 要有三个并发事件源：

1. grab events
2. prep events
3. decode results

每个 `FilledSlotEvent` 都必须经过：

1. `mark_filled`
2. prep / duplicate 判定
3. 若非 duplicate 则 `assign_decode`
4. decode 完成后 `complete_decode`
5. 释放 slot 给 grab

### 16.4 第四步：prep

prep 最小实现：

1. 从 slot 读一个较小 ROI
2. 计算 fingerprint
3. 与上次 fingerprint 比较
4. duplicate 立即释放
5. non-duplicate 进入 decode

### 16.5 第五步：decode worker pool

每个 decode worker：

1. 读 assignment
2. 从共享内存 slot 建 RGB view
3. 尝试 decode
4. 返回 `DecodeCompletion`

geometry 复用是可选增强，但 fixed-slot + generation 不是可选项。

### 16.6 第六步：assembler

assembler 只负责：

1. 按 `chunk_id` 去重
2. 收集 payload
3. 判断 complete

### 16.7 第七步：shutdown

必须实现：

1. stop flag
2. queue sentinel
3. process join/terminate/kill
4. queue close/join_thread
5. shared memory unlink

缺任一项，长时间跑完或 Ctrl+C 后都会留下残留。

## 17. 当前实现的实证结论

这一节合并了先前散落在多个 FPS/抓屏优化文档里的、**当前仍然成立**的结论。凡是已经与现实现不一致的实验记录，都不再单独保留。

### 17.1 现在可以确认的事实

基于当前仓库内的 probe、真实接收日志和针对不同 `decode-workers` 的 A/B：

1. 纯 `mss.grab()` 自身就有 wall-time 长尾。
2. `copy` 的真实 memcpy 开销很低，问题曾经主要出在 completion 调度，而不是 memcpy 本体。
3. 当前固定 copy worker 方案已经把 `copy_wait_ms` 压回很低。
4. `grab-only` runtime 与纯 `mss` probe 非常接近，说明 grab 子进程本身现在已经比较干净。
5. `full receiver` 在高速传输场景下明显比 `grab-only` 更差，说明系统级并发负载会继续抬高 `grab_ms.p95`。
6. `decode-workers` 增加会抬高 `grab_ms.p95`，即使 decode worker 是独立子进程。

### 17.2 三组基线实验

当前已跑过三类基线：

1. 纯 `mss` probe
   只测 `mss.grab()`，不跑 receiver runtime。
2. `grab-only` runtime probe
   跑真实 grab 子进程和 copy/slot 结构，但不跑完整 decode/coordinator 负载。
3. `full receiver`
   跑真实 layered live pipeline。

结论是：

1. `grab-only` 与纯 `mss` 很接近。
2. `full receiver` 明显更差。

这意味着当前系统剩余的 jitter，不再主要来自“grab/copy 结构本身是否写错”，而是来自：

1. `mss` / WindowServer 自身的长尾
2. full pipeline 并发负载引入的额外系统调度干扰

### 17.3 一个关键区分：raw_grab_fps 与 cap_fps

过去优化讨论里最容易混淆的点是：`raw_grab_fps` 和 `cap_fps` 不同义。

当前正确理解是：

1. `raw_grab_fps`
   代表 grab 子进程调用 `mss.grab()` 的实际节拍。
2. `cap_fps`
   代表成功完成 copy 并发出 `FilledSlotEvent` 的节拍。

因此：

1. `raw_grab_fps` 高而 `cap_fps` 低
   说明问题在 `grab -> copy_done -> coord_filled` 之间。
2. `raw_grab_fps` 和 `cap_fps` 一起掉
   更像 grab 本体、slot starvation 或系统抓屏链路出了问题。

### 17.4 为什么早期优化文档大多不再保留

历史上试过很多方向：

1. `asyncio.to_thread` copy
2. 通用 threadpool copy
3. memoryview / Python 循环 copy
4. 把 copy 责任向后挪

这些文档在当时有调试价值，但现在单独留着会误导，因为：

1. 它们记录的是中间态，而不是当前实现。
2. 很多文档的关键假设已经被实测推翻。
3. 当前设计文档已经把仍然成立的结论收编进来了。

### 17.5 当前参数哲学

这说明：

1. receiver 不是一个“decode worker 越多越好”的系统。
2. 当前机器上，最佳参数一定是“抓帧稳定性”和“decode 吞吐”之间的折中。
3. 如果目标是让 grab 尽量满负荷，优先做的不是继续堆 decode worker，而是先观察 `grab_ms.p95`、`raw_grab_fps` 和 `accepted_fps` 的平衡点。

## 18. 复现时必须保持的设计不变量

如果你想复刻这套 pipeline，下面这些不变量不能破：

1. 帧数据必须走共享内存，不要走大对象 queue。
2. 所有后续阶段都必须以 `slot_id + generation` 为准。
3. duplicate 必须在 decode 之前尽早处理。
4. slot 的释放必须由 coordinator 统一调度。
5. shutdown 必须同时处理 stop flag、sentinel、join 和 shared memory unlink。
6. `grab` 的职责必须保持窄，不要把复杂逻辑塞进去。

## 19. 一句话总结

这套 decoder pipeline 的本质是：

**一个以 grab 为节拍器、以固定共享内存 slot 为载体、以 coordinator 为状态路由器、以 early dedup 和 geometry lock 为主要优化手段的多进程事件系统。**

如果你理解了这四个点：

1. 固定 slot
2. generation
3. early dedup
4. geometry lock

那你就已经抓住了这套 pipeline 的骨架；其余模块只是围绕这四个原则展开的工程化实现。
