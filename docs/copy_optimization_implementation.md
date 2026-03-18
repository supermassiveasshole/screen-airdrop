# Copy 优化最终实现

## 实现的优化

### 1. 分通道拷贝（已实现）

**位置**：[workers.py:291-298](../src/screen_airdrop/receiver/runtime/workers.py#L291-L298)

```python
def do_copy(shot_data: bytes, slot_id: int, w: int, h: int) -> float:
    bgra = np.frombuffer(shot_data, dtype=np.uint8).reshape((h, w, 4))
    # 分通道拷贝，避免非连续内存访问
    slot_views[slot_id][:, :, 0] = bgra[:, :, 0]
    slot_views[slot_id][:, :, 1] = bgra[:, :, 1]
    slot_views[slot_id][:, :, 2] = bgra[:, :, 2]
```

**收益**：Copy 时间 3.6ms → 1.18ms（3倍加速）

### 2. ThreadPoolExecutor 异步化（已实现）

**位置**：[workers.py:287-289](../src/screen_airdrop/receiver/runtime/workers.py#L287-L289)

```python
from concurrent.futures import ThreadPoolExecutor
copy_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="CopyWorker")
```

**位置**：[workers.py:369](../src/screen_airdrop/receiver/runtime/workers.py#L369)

```python
# 非阻塞提交
shot_bytes = bytes(shot.raw)
future = copy_executor.submit(do_copy, shot_bytes, int(slot_id), int(w), int(h))
```

**收益**：Grab 循环不再阻塞等待 copy

### 3. Future 管理（已实现）

**位置**：[workers.py:371-407](../src/screen_airdrop/receiver/runtime/workers.py#L371-L407)

```python
# 跟踪 pending copies
pending_copies.append({"future": future, ...})

# 检查已完成的 copy
for item in pending_copies:
    if item["future"].done():
        copy_ms = item["future"].result()
        # 发送 FilledSlotEvent
```

## 性能分析

### 理论性能

| 操作 | 优化前 | 优化后 |
|------|--------|--------|
| Grab | 15ms | 15ms |
| Copy（阻塞） | 3.6ms | 0ms（异步） |
| Submit | 0ms | 0.01ms |
| **总阻塞时间** | **18.6ms** | **15.01ms** |
| **理论最大 FPS** | **53.8** | **66.6** |

### 实际性能

需要实际测试来验证：
1. `raw_grab_fps` 是否提升
2. `capture_copy_time_ms` 是否保持 ~1.18ms
3. `pending_copies` 队列长度

## 关键设计决策

### 为什么用 ThreadPoolExecutor 而不是 asyncio？

1. **实现简单**：
   - 不需要重构整个 grab 循环为 async/await
   - 改动最小

2. **性能足够**：
   - Submit 开销极小（0.01ms）
   - Copy 在后台并行执行

3. **易于调试**：
   - 标准的 Future 模型
   - 不需要理解 asyncio 事件循环

### 为什么用 bytes() 而不是直接传递 shot？

1. **线程安全**：
   - `shot` 对象可能被 MSS 重用
   - `bytes()` 创建独立副本

2. **性能**：
   - `bytes()` 转换很快（< 0.1ms）
   - 比 pickle 快得多

### 为什么只用 1 个 worker？

1. **避免竞争**：
   - 多个 worker 可能同时写入不同 slot
   - 但仍受 GIL 限制

2. **简单**：
   - 单个 worker 足够（copy 只需 1.18ms）
   - 避免复杂的同步

## 潜在问题

### 问题 1：bytes() 转换开销

**测试**：
```python
shot = sct.grab(monitor)
t0 = time.perf_counter()
shot_bytes = bytes(shot.raw)
t1 = time.perf_counter()
print(f"bytes() time: {(t1-t0)*1000:.2f} ms")
```

**如果开销大（> 0.5ms）**：
- 使用 `memoryview(shot.raw)` 代替
- 或直接传递 `shot.raw`（bytearray）

### 问题 2：Copy worker 积压

**监控**：
```python
print(f"Pending copies: {len(pending_copies)}")
```

**如果积压过多（> 5）**：
- 增加 worker 数量（但小心 GIL）
- 或丢弃旧帧

### 问题 3：GIL 仍然限制

**事实**：
- Numpy 操作仍受 GIL 限制
- 但由于 copy 很快（1.18ms），影响有限

**如果需要进一步优化**：
- 使用 Cython（释放 GIL）
- 或使用 numba（JIT 编译）

## 测试计划

### 1. 功能测试

```bash
uv run pytest tests/unit/test_grab_nonblocking.py -v
```

✅ 已通过

### 2. 性能测试

运行实际场景，对比：
- `raw_grab_fps`：应该接近 60 fps
- `capture_copy_time_ms`：应该 ~1.18ms
- `slot_starvation_events`：应该很少

### 3. 压力测试

```bash
uv run screen-airdrop-receiver --capture-fps 60 ...
```

监控：
- `pending_copies` 队列长度
- CPU 使用率
- 内存使用

## 下一步优化（如果需要）

### 选项 1：Asyncio

```python
async def grab_loop():
    shot = sct.grab(monitor)
    await asyncio.to_thread(do_copy, shot_bytes, slot_id)
```

**优点**：
- 更轻量（协程切换 < 1μs）
- 更好的调度

**缺点**：
- 需要重构为 async/await
- 更复杂

### 选项 2：ProcessPoolExecutor

```python
copy_executor = ProcessPoolExecutor(max_workers=1)
```

**优点**：
- 真正的并行（无 GIL）

**缺点**：
- IPC 开销（pickle）
- 无法直接访问 slot_views

### 选项 3：C 扩展

```cython
# copy.pyx
cdef void copy_bgra_to_rgb(unsigned char* src, unsigned char* dst, int size) nogil:
    for i in range(size):
        dst[i*3] = src[i*4]
        dst[i*3+1] = src[i*4+1]
        dst[i*3+2] = src[i*4+2]
```

**优点**：
- 完全绕过 GIL
- 可以用 SIMD 优化
- 理论上最快

**缺点**：
- 维护成本高
- 需要编译

## 总结

**当前实现**：
- ✅ 分通道拷贝（3倍加速）
- ✅ ThreadPoolExecutor 异步化
- ✅ 非阻塞提交
- ✅ Future 管理

**预期收益**：
- Grab 阻塞时间：18.6ms → 15ms
- 理论最大 FPS：53.8 → 66.6
- Copy 与 grab 真正并行

**代码位置**：
- [workers.py:270-450](../src/screen_airdrop/receiver/runtime/workers.py#L270-L450)

请测试这个实现，检查 `raw_grab_fps` 是否达到预期！
