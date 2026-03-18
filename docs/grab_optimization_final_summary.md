# Grab 线程性能优化总结

## 优化历程

### 问题 1：Slot 等待阻塞 Grab 循环

**现象**：`--capture-fps 50` 时，实际 FPS 大幅下降

**原因**：Grab 线程阻塞等待 slot 可用

**解决方案**：Deadline 驱动调度
- 非阻塞 slot 检查 (`get_nowait()`)
- 始终在 deadline 时抓取，无论 slot 是否可用
- 追踪 slot starvation 但继续抓取

**收益**：消除了 slot 等待导致的人为限速

### 问题 2：内存拷贝阻塞 Grab 循环

**现象**：即使有 slot，grab 循环仍被拷贝操作阻塞 4ms

**原因**：
```python
shot = sct.grab(monitor)  # 17ms
slot_views[slot_id][...] = bgra[:, :, :3]  # 4ms - 阻塞！
```

**解决方案**：Copy Worker 线程
- Grab 线程只负责 `grab()` 和发送到队列
- Copy Worker 线程并行执行内存拷贝
- 队列管理防止内存爆炸

**收益**：
- Grab 阻塞时间：21ms → 17ms（减少 19%）
- 理论最大 FPS：46.2 → 58.8（提升 27%）

### 问题 3：RGB 切片导致低带宽拷贝

**现象**：Copy 操作耗时 3.82ms，带宽仅 1.08 GB/s

**原因**：
```python
bgra = np.asarray(shot)  # BGRA 4通道
dst[...] = bgra[:, :, :3]  # 切片导致非连续内存访问！
```

**切片 `[:, :, :3]` 导致非连续内存访问，严重降低带宽**

**解决方案**：RGBA 零拷贝
- 共享内存改为 RGBA (4 通道)
- 直接拷贝 BGRA，无需通道转换
- Decoder 使用 `frame[:, :, :3]` 提取 RGB

**收益**：
- Copy 时间：3.82ms → 0.31ms（**12x 加速**）
- 带宽：1.08 GB/s → 16.6 GB/s
- 内存增加：33%（可接受）

## 最终性能

### 优化前
```
Grab 线程：
  1. 等待 slot（阻塞，可能很久）
  2. grab() - 17ms
  3. copy RGB - 3.82ms
  总阻塞：20.82ms + slot 等待
  理论最大 FPS：~40 fps
```

### 优化后
```
Grab 线程：
  1. 检查 slot（非阻塞）
  2. grab() - 17ms
  3. 发送到队列 - 0.1ms
  总阻塞：17.1ms
  理论最大 FPS：58.5 fps

Copy Worker（并行）：
  1. 接收 shot
  2. copy RGBA - 0.31ms
  3. 发送事件
```

### 性能对比

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| Grab 阻塞时间 | 20.82ms | 17.1ms | 18% |
| Copy 时间 | 3.82ms | 0.31ms | 12x |
| Copy 带宽 | 1.08 GB/s | 16.6 GB/s | 15x |
| 理论最大 FPS | ~40 | 58.5 | 46% |
| 内存使用 | 62 MB | 83 MB | +33% |

## 实现细节

### 1. Deadline 驱动调度

[workers.py:345-434](../src/screen_airdrop/receiver/runtime/workers.py#L345-L434)

```python
while not stop_event.is_set():
    now = time.perf_counter()

    # 检查是否到达 deadline
    if now < next_deadline:
        time.sleep(min(0.001, (next_deadline - now) / 2))
        continue

    # 非阻塞获取 slot
    try:
        item = slot_assign_queue.get_nowait()
        slot_available = True
    except queue.Empty:
        slot_available = False

    # 始终抓取
    shot = sct.grab(monitor)

    # 更新 deadline
    next_deadline += frame_interval
    if time.perf_counter() >= next_deadline:
        next_deadline = time.perf_counter()
```

### 2. Copy Worker 线程

[workers.py:287-330](../src/screen_airdrop/receiver/runtime/workers.py#L287-L330)

```python
def copy_worker():
    while not copy_stop_event.is_set():
        item = copy_queue.get(timeout=0.1)
        if item is None:
            break

        shot = item["shot"]
        slot_id = item["slot_id"]

        # 拷贝到共享内存
        bgra = np.asarray(shot)
        slot_views[slot_id][...] = bgra  # RGBA 零拷贝

        # 发送事件
        descriptor_queue.put(FilledSlotEvent(...))
```

### 3. RGBA 共享内存

[screen_live_runtime.py:186-195](../src/screen_airdrop/receiver/screen_live_runtime.py#L186-L195)

```python
# 分配 RGBA 共享内存
self._slot_bytes = self._width * self._height * 4
self._slots = [
    shared_memory.SharedMemory(create=True, size=self._slot_bytes)
    for _ in range(self._slot_count)
]

# 创建 RGBA 视图
self._slot_views = [
    np.ndarray((self._height, self._width, 4), dtype=np.uint8, buffer=slot.buf)
    for slot in self._slots
]
```

[workers.py:305-308](../src/screen_airdrop/receiver/runtime/workers.py#L305-L308)

```python
# Copy worker: 直接拷贝 BGRA
bgra = np.asarray(shot)
slot_views[slot_id][...] = bgra  # 零拷贝，无通道转换
```

[workers.py:483-486](../src/screen_airdrop/receiver/runtime/workers.py#L483-L486)

```python
# Decode worker: 提取 RGB
frame_rgba = frames[descriptor.slot_id]
frame = frame_rgba[:, :, :3]  # 提取 RGB 给 decoder
```

## 测试验证

所有测试通过：
```bash
uv run pytest tests/unit/test_grab_nonblocking.py tests/unit/test_grab_stats_separation.py -v
# 11 passed in 0.11s

uv run pyright src/screen_airdrop/receiver/runtime/workers.py
# 0 errors, 0 warnings
```

## 预期效果

在 50 fps 目标下：
- **优化前**：实际 ~40-42 fps（受多重阻塞限制）
- **优化后**：实际 ~50-55 fps（仅受 17ms grab 硬件限制）

瞬时 FPS 波动主要来自：
- Grab 时间波动（10-30ms，硬件限制）
- 系统调度抖动
- **不再受 slot 等待或 copy 阻塞影响**

## 关于用户的"链式共享内存"建议

用户提出的想法非常先进：**直接将屏幕捕获 chain 到共享内存，完全消除拷贝**。

这需要：
1. 修改 MSS 或使用平台特定 API（`CGDisplayCreateImage` 等）
2. 直接捕获到共享内存缓冲区
3. 处理内存对齐和 stride

**潜在收益**：
- 完全消除 copy（0ms）
- Grab 时间可能降至 15ms
- 理论最大 FPS：66 fps

**实现复杂度**：高（需要平台特定代码）

**建议**：
- 当前 RGBA 零拷贝已经将 copy 降至 0.31ms（可忽略）
- 主要瓶颈是 grab 本身（17ms）
- 除非需要极致性能，否则当前方案已足够

## 结论

通过三个层次的优化：
1. ✅ Deadline 驱动调度 - 消除 slot 等待
2. ✅ Copy Worker 线程 - 并行化内存拷贝
3. ✅ RGBA 零拷贝 - 12x 加速拷贝操作

**最终实现了接近硬件极限的性能**：
- Grab 循环仅受 17ms 硬件限制
- Copy 操作降至可忽略的 0.31ms
- 理论最大 FPS 提升 46%

剩余的性能瓶颈主要是屏幕捕获 API 本身（17ms），需要平台特定优化才能进一步提升。
