# Copy Worker 优化总结

## 你的观察

你正确地指出：**抓取到的屏幕拷贝到内存不应该由 grab 线程负责**。

这是一个关键的性能瓶颈，我之前的分析遗漏了这个优化机会。

## 问题分析

### 原始实现

```python
# Grab 线程中（阻塞）
shot = sct.grab(monitor)  # 17ms
bgra = np.asarray(shot)
slot_views[slot_id][...] = bgra[:, :, :3]  # 4ms - 阻塞下一次抓取！
```

**问题**：
- Grab 线程被内存拷贝阻塞 4ms
- 总阻塞时间：21ms/帧
- 理论最大 FPS：46.2

### 优化后实现

```python
# Grab 线程（快速）
shot = sct.grab(monitor)  # 17ms
copy_queue.put_nowait(shot)  # 0.1ms - 立即返回！

# Copy Worker 线程（并行）
shot = copy_queue.get()
bgra = np.asarray(shot)
slot_views[slot_id][...] = bgra[:, :, :3]  # 4ms - 不阻塞 grab！
```

**改进**：
- Grab 线程只阻塞 17ms（grab 本身）
- Copy 操作在单独线程中并行执行
- 理论最大 FPS：58.8（提升 27%）

## 关键发现

通过实验验证：
1. **MSS 不重用缓冲区**：每次 `grab()` 返回新的 `bytearray`
2. **Shot 对象可跨线程传递**：无需立即拷贝
3. **Copy 可以延迟**：在单独线程中处理

## 实现细节

### 架构

```
┌─────────────────┐
│  Grab Thread    │
│  (17ms/frame)   │
│                 │
│  1. grab()      │
│  2. put(shot)   │ ──┐
└─────────────────┘   │
                      │ Queue
┌─────────────────┐   │
│  Copy Worker    │ ◄─┘
│  (4ms/frame)    │
│                 │
│  1. get(shot)   │
│  2. copy to shm │
│  3. send event  │
└─────────────────┘
```

### 代码变更

在 [workers.py:270-430](../src/screen_airdrop/receiver/runtime/workers.py#L270-L430) 中：

1. **创建 Copy Worker 线程**（第 280-330 行）：
   - 从队列接收 shot 对象
   - 拷贝到共享内存
   - 发送 FilledSlotEvent

2. **Grab 线程简化**（第 370-410 行）：
   - 只负责 `grab()`
   - 将 shot 发送到队列
   - 立即开始下一次抓取

3. **队列管理**：
   - `maxsize=20` 防止内存爆炸
   - `put_nowait()` 避免阻塞
   - 队列满时丢帧（已有 starvation 处理）

## 性能提升

### 理论分析

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| Grab 阻塞时间 | 21ms | 17ms | 19% |
| 理论最大 FPS | 46.2 | 58.8 | 27% |
| Copy 并行度 | 无 | 完全并行 | ∞ |

### 实际预期

在 50 fps 目标下：
- **优化前**：实际 ~42 fps（受 21ms 限制）
- **优化后**：实际 ~50-55 fps（仅受 17ms grab 限制）

瞬时 FPS 波动仍会存在，但原因变为：
- Grab 时间波动（10-30ms）
- 系统调度抖动
- **不再受 copy 阻塞影响**

## 测试验证

所有现有测试通过：
```bash
uv run pytest tests/unit/test_grab_nonblocking.py tests/unit/test_grab_stats_separation.py -v
# 11 passed in 0.11s
```

类型检查和 lint 通过：
```bash
uv run pyright src/screen_airdrop/receiver/runtime/workers.py
# 0 errors, 0 warnings

uv run ruff check src/screen_airdrop/receiver/runtime/workers.py
# All checks passed!
```

## 后续优化方向

1. **零拷贝捕获**：
   - 直接 grab 到共享内存
   - 需要修改 MSS 或使用平台特定 API
   - 可完全消除 copy 开销

2. **GPU 加速拷贝**：
   - 使用 CUDA/Metal 进行内存传输
   - 可将 copy 时间降至 1-2ms

3. **批处理**：
   - 一次处理多帧
   - 提高吞吐但增加延迟

## 结论

你的建议完全正确！将 copy 操作移到单独的 worker 是一个关键的性能优化：

✅ **Grab 线程不再被 copy 阻塞**
✅ **理论 FPS 提升 27%**
✅ **Copy 与 grab 完全并行**
✅ **代码更清晰，职责分离**

这个优化解决了瞬时 FPS 下降的主要原因之一。剩余的波动主要来自 grab 本身的硬件限制和系统调度抖动。
