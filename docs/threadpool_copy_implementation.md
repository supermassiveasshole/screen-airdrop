# 异步 Copy 实现 - ThreadPoolExecutor

## 实现方案

基于你的建议，我实现了 **ThreadPoolExecutor** 方案，将 copy 操作异步化。

### 核心思路

```python
# Grab 线程主循环
shot = sct.grab(monitor)  # 17ms

# 提交 copy 到线程池（非阻塞，立即返回）
future = copy_executor.submit(do_copy, shot_bytes, slot_id, w, h)

# 立即继续下一次 grab，不等待 copy 完成
# Copy 在后台线程中并行执行
```

### 关键设计

1. **ThreadPoolExecutor（1 worker）**：
   - 单个 worker 线程专门处理 copy
   - 避免多线程竞争
   - 比创建/销毁线程更高效

2. **非阻塞提交**：
   - `submit()` 立即返回 Future
   - Grab 线程不等待 copy 完成
   - 真正的异步执行

3. **Future 管理**：
   - 跟踪 pending copies
   - 每次循环检查已完成的 copy
   - 发送 FilledSlotEvent

4. **数据传递**：
   - 将 `shot.raw` 转为 `bytes`
   - 在 worker 线程中重建 numpy 数组
   - 避免跨线程共享 numpy 对象

### 性能优势

| 操作 | 优化前 | 优化后 |
|------|--------|--------|
| Grab | 17ms | 17ms |
| Copy（阻塞） | 1.18ms | 0ms（异步） |
| **总阻塞时间** | **18.18ms** | **17ms** |
| **理论最大 FPS** | **55** | **58.8** |

### 为什么比之前的 Thread 方案好？

1. **专用 worker**：
   - 单个 worker 线程，避免线程创建开销
   - 线程池复用，更高效

2. **更好的调度**：
   - ThreadPoolExecutor 的调度比手动 Thread 更优
   - 自动管理线程生命周期

3. **简单的 Future 模型**：
   - 不需要手动管理队列
   - Future.done() 检查非常高效

### 与 Asyncio 对比

| 特性 | ThreadPoolExecutor | Asyncio |
|------|-------------------|---------|
| 实现复杂度 | 低 | 中 |
| 性能 | 好 | 更好 |
| GIL 影响 | 有（但可接受） | 无（单线程） |
| 调试难度 | 低 | 高 |
| 代码改动 | 小 | 大（需要 async/await） |

**选择 ThreadPoolExecutor 的原因**：
- 实现简单，改动小
- 性能已经足够好
- 不需要重构整个 grab 循环为 async

### 代码实现

```python
# 创建线程池
copy_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="CopyWorker")

def do_copy(shot_data: bytes, slot_id: int, w: int, h: int) -> float:
    """在线程池中执行 copy"""
    t0 = time.perf_counter()
    bgra = np.frombuffer(shot_data, dtype=np.uint8).reshape((h, w, 4))
    # 分通道拷贝（1.18ms）
    slot_views[slot_id][:, :, 0] = bgra[:, :, 0]
    slot_views[slot_id][:, :, 1] = bgra[:, :, 1]
    slot_views[slot_id][:, :, 2] = bgra[:, :, 2]
    t1 = time.perf_counter()
    return (t1 - t0) * 1000.0

# Grab 循环
shot = sct.grab(monitor)
shot_bytes = bytes(shot.raw)  # 快速转换

# 异步提交（非阻塞）
future = copy_executor.submit(do_copy, shot_bytes, slot_id, w, h)
pending_copies.append({"future": future, ...})

# 检查已完成的 copy
for item in pending_copies:
    if item["future"].done():
        copy_ms = item["future"].result()
        # 发送 FilledSlotEvent
```

### 潜在问题和解决方案

#### 问题 1：bytes() 转换开销

**测试**：
```python
shot = sct.grab(monitor)
t0 = time.perf_counter()
shot_bytes = bytes(shot.raw)
t1 = time.perf_counter()
print(f"bytes() conversion: {(t1-t0)*1000:.2f} ms")
```

**如果开销大**：
- 直接传递 `shot.raw`（bytearray）
- 或使用 memoryview

#### 问题 2：Worker 线程落后

**现象**：Copy worker 处理速度 < Grab 速度

**解决**：
- 监控 `len(pending_copies)`
- 如果积压过多，丢弃旧帧
- 或增加 worker 数量（但要小心 GIL）

#### 问题 3：GIL 仍然存在

**事实**：
- Numpy 操作仍受 GIL 限制
- 但由于 copy 很快（1.18ms），影响有限

**如果需要进一步优化**：
- 使用 Cython 实现 copy（释放 GIL）
- 或使用 numba（JIT 编译）

### 测试建议

1. **监控指标**：
   - `capture_copy_time_ms`：应该保持 ~1.18ms
   - `raw_grab_fps`：应该接近 58 fps
   - `len(pending_copies)`：应该 < 3

2. **压力测试**：
   - 设置 `--capture-fps 60`
   - 检查是否有 copy 积压
   - 监控 slot starvation

3. **对比测试**：
   - 对比优化前后的 `raw_grab_fps`
   - 检查 `capture_grab_time_ms` 是否降低

### 下一步优化（如果需要）

如果 ThreadPoolExecutor 还不够快：

1. **Asyncio + to_thread**：
   ```python
   async def grab_loop():
       shot = sct.grab(monitor)
       await asyncio.to_thread(do_copy, shot_bytes, slot_id)
   ```

2. **ProcessPoolExecutor**：
   - 真正的并行（无 GIL）
   - 但 IPC 开销可能更大

3. **C 扩展**：
   - 用 Cython 实现 copy
   - 完全绕过 GIL
   - 可以用 SIMD 优化

## 总结

**当前实现**：
- ✅ ThreadPoolExecutor 异步 copy
- ✅ 分通道拷贝（1.18ms）
- ✅ 非阻塞提交
- ✅ Grab 循环不等待 copy

**预期收益**：
- Grab 阻塞时间：18.18ms → 17ms
- 理论最大 FPS：55 → 58.8
- Copy 与 grab 真正并行

**优势**：
- 实现简单，改动小
- 性能提升明显
- 易于调试和维护

请测试这个实现，看看 `raw_grab_fps` 是否达到预期！
