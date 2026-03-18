# 零拷贝优化方案 - Asyncio 实现

## 问题分析

### 为什么 Thread 方案失败了？

1. **GIL 限制**：
   - Python 的 GIL 导致多线程无法真正并行
   - 即使 copy 是 IO-bound，numpy 操作仍受 GIL 影响
   - Thread 方案实际上是串行执行，没有性能提升

2. **RGBA 方案的问题**：
   - 虽然 copy 时间从 3.82ms → 0.31ms
   - 但内存增加 33%，可能导致缓存失效
   - Decode worker 的切片操作 `[:, :, :3]` 可能引入新开销

### 为什么不用 Process？

1. **无法共享变量**：
   - `shot` 对象无法直接跨进程传递
   - 需要 pickle 序列化，开销比 copy 还大
   - 共享内存需要预先分配，无法动态传递

2. **Prep process 的限制**：
   - Prep process 接收 `FilledSlotEvent`
   - 这意味着 grab 已经完成 copy
   - 无法在 prep 中做 copy

## 正确的方案：Asyncio

### 为什么 Asyncio 更好？

1. **轻量级**：
   - 协程切换开销极小（微秒级）
   - 无需 GIL（单线程内调度）
   - 内存开销小

2. **适合 IO-bound**：
   - Copy 操作是内存 IO
   - Asyncio 可以在 copy 时让出控制权
   - 实现真正的并发

3. **共享内存**：
   - 同一进程内，可以直接访问 `shot` 和 `slot_views`
   - 无需序列化或 IPC

### 实现方案

```python
import asyncio

async def grab_loop():
    """Grab 协程：只负责抓取"""
    while not stop:
        # 等待 slot
        slot_id = await get_slot_async()

        # Grab（同步操作，但很快）
        shot = sct.grab(monitor)

        # 提交 copy 任务（异步）
        asyncio.create_task(copy_and_send(shot, slot_id))

async def copy_and_send(shot, slot_id):
    """Copy 协程：异步拷贝"""
    # 在 executor 中执行 copy（避免阻塞事件循环）
    await asyncio.to_thread(do_copy, shot, slot_id)

    # 发送事件
    descriptor_queue.put(FilledSlotEvent(...))

def do_copy(shot, slot_id):
    """实际的 copy 操作"""
    bgra = np.asarray(shot)
    slot_views[slot_id][...] = bgra[:, :, :3]
```

### 关键优化点

1. **`asyncio.to_thread`**：
   - 在线程池中执行 copy
   - 避免阻塞事件循环
   - 利用 OS 的线程调度

2. **`create_task`**：
   - 立即返回，不等待 copy 完成
   - Grab 循环可以继续下一次抓取
   - 真正的并发

3. **队列管理**：
   - 使用 `asyncio.Queue` 管理 slot
   - 非阻塞操作
   - 自动背压控制

## 实现细节

### 改造 grab_thread_main

```python
def _grab_thread_main(...):
    # 在线程中运行 asyncio 事件循环
    asyncio.run(_grab_async_main(...))

async def _grab_async_main(...):
    # 创建 asyncio 队列
    slot_queue = asyncio.Queue()

    # 启动 slot 提供者
    asyncio.create_task(slot_provider(slot_queue))

    # 启动 grab 循环
    await grab_loop(slot_queue)

async def grab_loop(slot_queue):
    with mss.mss() as sct:
        while not stop:
            # 非阻塞获取 slot
            try:
                slot_id = slot_queue.get_nowait()
            except asyncio.QueueEmpty:
                # 无 slot，继续抓取但不保存
                shot = sct.grab(monitor)
                continue

            # 抓取
            shot = sct.grab(monitor)

            # 异步 copy（不等待）
            asyncio.create_task(copy_task(shot, slot_id))

async def copy_task(shot, slot_id):
    # 在线程池中执行 copy
    await asyncio.to_thread(
        lambda: slot_views[slot_id].__setitem__(
            Ellipsis,
            np.asarray(shot)[:, :, :3]
        )
    )

    # 发送事件
    descriptor_queue.put(FilledSlotEvent(...))
```

## 预期收益

1. **Grab 循环不阻塞**：
   - Grab 后立即返回
   - Copy 在后台异步执行
   - 理论 FPS：1000/15 = 66 fps

2. **轻量级并发**：
   - 协程切换开销 < 1μs
   - 无 GIL 限制（单线程）
   - 内存开销小

3. **自动背压**：
   - 队列满时自动丢帧
   - 无需手动管理

## 风险

1. **`asyncio.to_thread` 仍受 GIL 限制**：
   - 但比纯 Thread 好（事件循环调度更高效）
   - 可以考虑用 `ProcessPoolExecutor`

2. **事件循环开销**：
   - 每次 `create_task` 有微小开销
   - 但远小于 Thread 创建

3. **复杂度增加**：
   - Asyncio 代码更难调试
   - 需要仔细处理异常

## 替代方案：直接用 RGBA + 优化切片

如果 asyncio 太复杂，可以：

1. **保持 RGBA 共享内存**
2. **优化 decode worker 的切片**：
   ```python
   # 不要每次都切片
   frame_rgba = frames[descriptor.slot_id]

   # 使用 view 而不是 copy
   frame_rgb = frame_rgba[:, :, :3]  # 这是 view，不是 copy

   # 或者让 decoder 直接处理 RGBA
   decoded = decoder.decode_frame(frame_rgba)  # 修改 decoder
   ```

3. **测量实际开销**：
   - 切片操作应该是零开销（view）
   - 如果有开销，说明 decoder 内部有问题

## 建议

1. **先测试 RGBA + 优化切片**：
   - 最简单
   - 理论上应该有效
   - 如果还是慢，说明问题在别处

2. **如果还不行，用 asyncio**：
   - 更复杂但更强大
   - 真正的异步并发

3. **最后考虑 C 扩展**：
   - 用 Cython 或 C 实现 copy
   - 完全绕过 GIL
   - 但维护成本高
