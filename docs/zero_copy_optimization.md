# 零拷贝优化方案分析

## 当前性能瓶颈

### 实测数据

| 方法 | 耗时 | 带宽 | 加速比 |
|------|------|------|--------|
| RGB slice copy (当前) | 3.82 ms | 1.08 GB/s | 1x |
| RGB per-channel copy | 1.25 ms | 3.3 GB/s | 3x |
| **RGBA 直接拷贝** | **0.31 ms** | **16.6 GB/s** | **12x** |

### 问题根源

当前代码：
```python
bgra = np.asarray(shot)  # BGRA 4通道
dst[...] = bgra[:, :, :3]  # 拷贝 + 去掉 alpha = 非连续内存访问
```

**切片 `[:, :, :3]` 导致非连续内存访问，严重降低带宽！**

## 优化方案对比

### 方案 1：改用 RGBA 共享内存（推荐）

**实现**：
```python
# 在 screen_live_runtime.py 中
self._slot_views = [
    np.ndarray((self._height, self._width, 4), dtype=np.uint8, buffer=slot.buf)
    for slot in self._slots
]

# 在 copy worker 中
bgra = np.asarray(shot)
slot_views[slot_id][...] = bgra  # 直接拷贝，无需通道转换
```

**优点**：
- ✅ 拷贝时间：3.82ms → 0.31ms（**12x 加速**）
- ✅ 带宽：1.08 GB/s → 16.6 GB/s
- ✅ 实现简单，只需改 shape
- ✅ 下游可以忽略 alpha 通道

**缺点**：
- ❌ 内存增加 33%（3 通道 → 4 通道）
- ❌ 需要修改下游代码（decoder 等）

**影响分析**：
- 内存增加：对于 10 个 slot，1920x1080 分辨率
  - RGB: 10 × 1920 × 1080 × 3 = 62 MB
  - RGBA: 10 × 1920 × 1080 × 4 = 83 MB
  - 增加：21 MB（可接受）

### 方案 2：链式共享内存（用户建议）

**概念**：
```
MSS 内部缓冲区 → 直接映射为共享内存 → 下游直接读取
                 (无拷贝)
```

**挑战**：

1. **MSS 不支持外部缓冲区**：
   - MSS 内部分配 `bytearray`
   - 无法指定目标缓冲区
   - 需要修改 MSS 源码或使用更底层的 API

2. **平台特定实现**：
   - macOS: `CGDisplayCreateImage` → `CGDataProviderCopyData`
   - Windows: `DXGI Desktop Duplication API`
   - Linux: `XGetImage` 或 `DRM`

3. **内存对齐问题**：
   - 共享内存需要页对齐（4KB）
   - 屏幕捕获可能有不同的对齐要求
   - 需要处理 stride/padding

**实现复杂度**：
- 🔴 需要平台特定代码
- 🔴 需要修改或替换 MSS
- 🔴 需要处理内存对齐
- 🟡 可能需要 C 扩展

**潜在收益**：
- ✅ 完全消除拷贝（0ms）
- ✅ 理论最大 FPS：1000/17 = 58.8 fps

### 方案 3：使用 memoryview 和 buffer protocol

**概念**：
```python
# 使用 Python buffer protocol 避免拷贝
shot_mv = memoryview(shot.rgb)  # 零拷贝视图
slot_mv = memoryview(slot_views[slot_id])
slot_mv[:] = shot_mv  # 可能仍需拷贝，但更高效
```

**测试**：
```python
import mss
import numpy as np
import time

with mss.mss() as sct:
    monitor = sct.monitors[1]
    h, w = monitor["height"], monitor["width"]
    dst = np.empty((h, w, 4), dtype=np.uint8)

    times = []
    for _ in range(10):
        shot = sct.grab(monitor)
        t0 = time.perf_counter()
        # 使用 buffer protocol
        dst_mv = memoryview(dst).cast('B')
        shot_mv = memoryview(shot.raw).cast('B')
        dst_mv[:] = shot_mv
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)

    print(f"memoryview copy: {sum(times)/len(times):.2f} ms")
```

### 方案 4：异步 DMA（终极方案）

**概念**：
使用 GPU 或 DMA 引擎进行异步内存传输。

**实现**：
- macOS: Metal `MTLBlitCommandEncoder`
- CUDA: `cudaMemcpyAsync`
- 需要 GPU 支持

**复杂度**：🔴🔴🔴 极高

## 推荐实施路线

### Phase 1：RGBA 零拷贝（立即实施）

**改动点**：
1. `screen_live_runtime.py`: 改 slot shape 为 (h, w, 4)
2. `workers.py`: 移除 `[:, :, :3]` 切片
3. Decoder: 忽略第 4 通道或适配

**预期收益**：
- Copy 时间：3.82ms → 0.31ms
- Grab 循环：17ms（仅受 grab 限制）
- 理论最大 FPS：58.8 fps

**风险**：低（只是改 shape）

### Phase 2：平台特定零拷贝（长期）

**目标**：
直接从屏幕捕获 API 写入共享内存。

**实现**：
- macOS: 使用 `CGDisplayCreateImage` + `CGDataProviderCopyData`
- 需要 C 扩展或 ctypes

**预期收益**：
- 完全消除拷贝（0ms）
- Grab 时间可能降至 15ms

**风险**：高（平台特定，维护成本）

## 结论

**立即实施方案 1（RGBA 零拷贝）**：
- 实现简单（改几行代码）
- 收益巨大（12x 加速）
- 风险低
- 内存增加可接受（21 MB）

**长期考虑方案 2（链式共享内存）**：
- 需要平台特定实现
- 完全消除拷贝
- 维护成本高

**不推荐方案 3 和 4**：
- 收益不明显或实现过于复杂
