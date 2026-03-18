# Grab Statistics Separation

## 问题背景

在原始的 slot-based runtime 实现中，`raw_grab_frames` 和 `captured` 在同一处累加，导致无法区分：
- **真实抓屏速率**（grab 线程的实际工作速率）
- **成功入队速率**（成功分配到 slot 的帧数）

这导致了两个问题：
1. 当 slot 池满时，grab 被反压阻塞，`cap_fps` 下降，但无法判断是 MSS 变慢还是下游反压
2. `copy_ms` 统计缺失，无法观察 BGR 转换的开销

## 解决方案

### 统计指标分离

**修改前**（[coordinator.py:241-246](src/screen_airdrop/receiver/runtime/coordinator.py#L241-L246)）：
```python
# 在 FilledSlotEvent 处理时同时更新两个计数器
with self._stats._lock:
    self._stats.captured += 1
    self._stats.raw_grab_frames += 1  # 错误：应该在 grab 时更新
    self._stats.capture_grab_time_ms += float(event.grab_ms)
    self._stats.capture_grab_ops += 1
```

**修改后**：
```python
# 1. 在 grab 完成后立即发送 raw_grab_stats 事件
descriptor_queue.put({
    "kind": "raw_grab_stats",
    "grab_ms": grab_ms,
})

# 2. coordinator 分别处理
# 处理 raw_grab_stats（真实抓屏）
if isinstance(event, dict) and event.get("kind") == "raw_grab_stats":
    with self._stats._lock:
        self._stats.raw_grab_frames += 1
        self._stats.capture_grab_time_ms += float(event.get("grab_ms", 0.0))
        self._stats.capture_grab_ops += 1
    return

# 处理 FilledSlotEvent（成功分配 slot）
if isinstance(event, FilledSlotEvent):
    with self._stats._lock:
        self._stats.captured += 1
        # raw_grab_frames 已在上面更新
```

### 恢复 copy_ms 统计

**修改前**：
```python
# grab 线程中没有统计 copy 时间
bgra = np.asarray(shot)
slot_views[int(slot_id)][...] = bgra[:, :, :3]
```

**修改后**：
```python
# 1. 在 grab 线程中统计 copy 时间
t1 = time.perf_counter()
bgra = np.asarray(shot)
slot_views[int(slot_id)][...] = bgra[:, :, :3]
t2 = time.perf_counter()
copy_ms = (t2 - t1) * 1000.0

# 2. 在 FilledSlotEvent 中传递 copy_ms
event = FilledSlotEvent(
    descriptor=...,
    grab_ms=grab_ms,
    copy_ms=copy_ms,  # 新增字段
)

# 3. coordinator 更新统计
with self._stats._lock:
    self._stats.captured += 1
    self._stats.capture_copy_time_ms += float(event.copy_ms)
    self._stats.capture_copy_ops += 1
```

## 效果

### 统计指标语义

- **`raw_grab_frames`**：grab 线程实际调用 `mss.grab()` 的次数（不受 slot 池影响）
- **`captured`**：成功分配到 slot 并入队的帧数（受 slot 池反压影响）
- **`raw_grab_fps`**：真实抓屏速率 = `Δraw_grab_frames / Δtime`
- **`cap_fps`**：成功入队速率 = `Δcaptured / Δtime`

### 诊断能力提升

**场景 1：MSS 本身变慢**
```
raw_grab_fps: 30.0  ← 真实抓屏速率正常
cap_fps: 30.0       ← 入队速率也正常
grab_ms: 33.3       ← 每次 grab 耗时正常
prep_backlog: 0     ← 无积压
```

**场景 2：Slot 池反压**
```
raw_grab_fps: 45.0  ← 真实抓屏速率高（如果没有反压）
cap_fps: 30.0       ← 入队速率被限制
grab_ms: 15.0       ← 每次 grab 很快
prep_backlog: 5     ← 有积压
captured < raw_grab_frames  ← 有帧因 slot 满而未入队
```

**场景 3：MSS 变慢 + 反压**
```
raw_grab_fps: 25.0  ← 真实抓屏速率低
cap_fps: 25.0       ← 入队速率也低
grab_ms: 40.0       ← 每次 grab 耗时长（问题根源）
prep_backlog: 0     ← 无积压（因为 grab 本身慢）
```

## 代码变更

### 修改的文件

1. **[runtime/events.py](src/screen_airdrop/receiver/runtime/events.py)**
   - `FilledSlotEvent` 添加 `copy_ms` 字段

2. **[runtime/workers.py](src/screen_airdrop/receiver/runtime/workers.py)**
   - **正常路径**（有 slot）：只发送 `FilledSlotEvent`，不发送 `raw_grab_stats`
   - **饥饿路径**（无 slot）：发送 `raw_grab_stats` 事件
   - 统计 `copy_ms` 并传递给 `FilledSlotEvent`

3. **[runtime/coordinator.py](src/screen_airdrop/receiver/runtime/coordinator.py)**
   - `_handle_grab_event` 处理 `raw_grab_stats`（仅在 starvation 时）
   - `FilledSlotEvent` 同时更新 `raw_grab_frames` 和 `captured`
   - 更新 `capture_copy_time_ms` 和 `capture_copy_ops`

### 统计更新逻辑

**正常路径**（有 slot 可用）：
```python
# FilledSlotEvent 处理
raw_grab_frames += 1  # 计入总抓屏次数
captured += 1         # 计入成功入队次数
```

**饥饿路径**（slot 池满）：
```python
# raw_grab_stats 事件处理
raw_grab_frames += 1  # 计入总抓屏次数
# captured 不增加（因为没有 slot）

# grab_slot_starvation 事件处理
dropped_slot_starvation += 1
slot_starvation_events += 1
```

**关键点**：
- 每次 grab 只更新一次 `raw_grab_frames`
- 只有成功分配 slot 时才更新 `captured`
- 保证 `raw_grab_frames >= captured`

### 新增的测试

- **[tests/unit/test_grab_stats_separation.py](tests/unit/test_grab_stats_separation.py)**
  - 验证 `raw_grab_frames` 和 `captured` 分离
  - 验证 slot 池满时的统计行为
  - 验证 `copy_ms` 计算

## 向后兼容性

- ✅ 所有现有字段保持不变
- ✅ `FilledSlotEvent.copy_ms` 有默认值 0.0，不破坏现有代码
- ✅ 统计快照格式不变
- ✅ 进度报告格式不变

## 后续工作

### ✅ P1: Grab 非阻塞机制（已完成）

**实现内容**：
- Grab 线程使用短超时（50ms）获取 slot
- Slot 池满时不阻塞，继续抓屏并更新 `raw_grab_frames`
- 发送 `grab_slot_starvation` 事件通知 coordinator
- 新增统计字段：
  - `dropped_slot_starvation`：因 slot 池满而跳过的帧数
  - `slot_starvation_events`：slot 饥饿事件次数

**代码变更**：
- [runtime/workers.py](src/screen_airdrop/receiver/runtime/workers.py)：实现非阻塞 grab
- [runtime/coordinator.py](src/screen_airdrop/receiver/runtime/coordinator.py)：处理 starvation 事件
- [runtime/stats.py](src/screen_airdrop/receiver/runtime/stats.py)：新增统计字段

**效果**：
```bash
# 场景：Slot 池满，下游慢
raw_grab_fps=45.0           # Grab 继续工作，不被阻塞
cap_fps=30.0                # 实际入队速率
dropped_slot_starvation=150 # 丢弃的帧数
slot_starvation_events=150  # 饥饿事件次数
starvation_rate=15%         # 饥饿率 = dropped / raw_grab_frames
```

### P2: 进一步优化（可选）

如果需要更激进的优化，可以考虑：
- 主动回收最旧的 pending slot（类似旧版的 drop-oldest 策略）
- 动态调整 slot 池大小
- 根据 starvation_rate 自动调整 capture_fps
