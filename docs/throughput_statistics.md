# 传输速率统计说明

## 关键指标

### 帧级别统计
- **`decoded`**：成功解码的总帧数（包括重复帧）
- **`assembled`**：成功组装的**新 chunk** 数量（去重后）
- **`dedup`**：重复帧数量（frame-level deduplication）

### 速率指标

#### 1. 帧解码速率
- **`dec_fps`**：总解码速率 = `Δdecode_ok / Δtime`
  - 包括所有成功解码的帧（含重复）
  - 反映解码器的工作负载

#### 2. 有效数据接收速率
- **`new_chunk_fps`**：新 chunk 接收速率 = `Δdecoded_new_chunks / Δtime`
  - **只统计新 chunk**（去重后）
  - 反映真实的有效数据接收速率
  - 这是最重要的性能指标

- **`rx_KBps`**：有效数据吞吐量 = `Δassembled_bytes / Δtime / 1024`
  - 基于 `assembled_bytes`（只统计新 chunk 的字节数）
  - 反映真实的数据传输速率（KB/s）

### 关系

```
dec_fps >= new_chunk_fps
```

**原因**：
- `dec_fps` 包括所有解码成功的帧（含重复）
- `new_chunk_fps` 只包括新 chunk
- 差值 = 重复 chunk 的解码速率

**示例**：
```bash
decoded=203 assembled=201 dedup=242
dec_fps=19.79 new_chunk_fps=19.58
rx_KBps=142.01

分析：
- 总解码速率：19.79 fps
- 有效数据速率：19.58 fps（新 chunk）
- 重复率：(203-201)/203 = 0.99% (chunk-level)
- 帧重复率：242/448 = 54% (frame-level，包括 prep 阶段的去重)
```

## 统计实现

### Coordinator 中的逻辑

```python
# 解码成功后
if completion.frame_type == 1:  # FRAME_DATA
    is_new = self._assembler.add(completion.chunk_id, completion.payload)

    with self._stats._lock:
        if is_new:
            # 新 chunk：更新有效数据统计
            self._stats.decoded_new_chunks += 1
            self._stats.assembled += 1
            self._stats.assembled_bytes += len(completion.payload)
        else:
            # 重复 chunk：只统计重复次数
            self._stats.decoded_duplicate_chunks += 1
```

### 关键点

1. **`assembled_bytes` 只统计新 chunk**
   - 重复 chunk 不会累加到 `assembled_bytes`
   - 因此 `rx_KBps` 是真实的有效数据速率

2. **两级去重**
   - **Frame-level dedup**（prep 阶段）：通过指纹去重，避免重复解码相同的帧
   - **Chunk-level dedup**（assembler）：通过 chunk_id 去重，避免重复组装相同的 chunk

3. **为什么需要两级去重？**
   - Frame-level：同一帧可能被多次抓取（发送端循环播放）
   - Chunk-level：不同帧可能包含相同的 chunk（发送端重复发送）

## 输出格式

```bash
captured=448 decoded=203 assembled=201 missing=107 dropped=0/0 dedup=242
cap_fps=33.64 raw_grab_fps=33.64 prep_fps=33.64 accepted_fps=19.79
dec_fps=19.79 new_chunk_fps=19.58
prep_backlog=0 overwrite=0 decode_q=3
rx_KBps=142.01 grab_ms=21.89 copy_ms=5.27 ...
```

**关键指标解读**：
- `dec_fps=19.79`：解码器每秒处理 19.79 帧
- `new_chunk_fps=19.58`：每秒接收 19.58 个新 chunk（有效数据）
- `rx_KBps=142.01`：有效数据吞吐量 142 KB/s
- `dedup=242`：prep 阶段去重了 242 个重复帧
- `assembled=201`：成功组装了 201 个新 chunk

## 性能分析

### 场景 1：高重复率（发送端循环播放）
```bash
decoded=500 assembled=100 dedup=800
dec_fps=50.0 new_chunk_fps=10.0
→ 大量重复帧，有效数据速率低
```

### 场景 2：低重复率（发送端单次播放）
```bash
decoded=500 assembled=490 dedup=10
dec_fps=50.0 new_chunk_fps=49.0
→ 几乎无重复，有效数据速率高
```

### 场景 3：解码瓶颈
```bash
dec_fps=10.0 new_chunk_fps=9.8
decode_q=20 prep_backlog=0
→ 解码器慢，但去重率低
```

## 总结

- **`rx_KBps`** 和 **`new_chunk_fps`** 是最重要的性能指标
- 它们只统计新 chunk，反映真实的有效数据传输速率
- `dec_fps` 包括重复 chunk，反映解码器的工作负载
- 两者的差值反映了 chunk-level 的重复率
