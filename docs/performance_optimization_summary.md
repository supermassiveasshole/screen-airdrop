# Screen-Airdrop Receiver Performance Optimization

## 问题诊断

根据 Codex 的分析，`cap_fps` 下降的根本原因是：

### 1. 架构语义变化
- **旧版**：队列满时丢旧帧，grab 不停 → `cap_fps` 反映真实抓屏能力
- **新版**：slot 池耗尽时 grab 被反压阻塞 → `cap_fps` 被下游速度限制

### 2. 统计可观测性退化
- `captured` 和 `raw_grab_frames` 在同一处累加，无法区分"抓屏速率"和"接受速率"
- `copy_ms` 未统计，显示为 0
- `dedup_ms` 只统计决策时间，不含指纹计算

### 3. 调度路径变长
- 旧版：`grab -> copy -> dedup -> queue`
- 新版：`grab -> descriptor_queue -> coordinator -> prep_strategy -> ... -> decode`

## 优化方案

### ✅ P0: 统计指标分离（已完成）

**目标**：区分真实抓屏速率和成功入队速率

**实现**：
1. **分离统计时机**：
   - `raw_grab_frames`：在 grab 完成后立即更新（不受 slot 池影响）
   - `captured`：在成功分配 slot 后更新（受 slot 池反压影响）

2. **恢复 copy_ms 统计**：
   - 在 grab 线程中统计 BGR 转换时间
   - 通过 `FilledSlotEvent.copy_ms` 传递给 coordinator

**代码变更**：
- [runtime/events.py](src/screen_airdrop/receiver/runtime/events.py)：添加 `copy_ms` 字段
- [runtime/workers.py](src/screen_airdrop/receiver/runtime/workers.py)：发送 `raw_grab_stats` 事件
- [runtime/coordinator.py](src/screen_airdrop/receiver/runtime/coordinator.py)：分别处理统计

**效果**：
```bash
# 现在可以区分三种场景：

# 场景 1：MSS 本身变慢
raw_grab_fps=30.0 cap_fps=30.0 grab_ms=33.3 prep_backlog=0
→ MSS 性能正常，无反压

# 场景 2：Slot 池反压
raw_grab_fps=45.0 cap_fps=30.0 grab_ms=15.0 prep_backlog=5
→ MSS 很快，但被下游反压限制

# 场景 3：MSS 变慢 + 反压
raw_grab_fps=25.0 cap_fps=25.0 grab_ms=40.0 prep_backlog=0
→ MSS 本身慢（问题根源），无反压
```

### ✅ P1: Grab 非阻塞机制（已完成）

**目标**：让 grab 在 slot 池满时不阻塞，保持高 `raw_grab_fps`

**实现**：
1. **短超时获取 slot**：
   - 从 `timeout=1.0s` 改为 `timeout=0.05s`
   - Slot 池满时快速超时，不长时间阻塞

2. **继续抓屏**：
   - 超时后仍然调用 `mss.grab()` 并更新 `raw_grab_frames`
   - 发送 `grab_slot_starvation` 事件通知 coordinator
   - 帧数据不存储（因为没有 slot），但统计继续

3. **新增统计字段**：
   - `dropped_slot_starvation`：因 slot 池满而跳过的帧数
   - `slot_starvation_events`：slot 饥饿事件次数

**代码变更**：
- [runtime/workers.py](src/screen_airdrop/receiver/runtime/workers.py)：实现非阻塞 grab
- [runtime/coordinator.py](src/screen_airdrop/receiver/runtime/coordinator.py)：处理 starvation 事件
- [runtime/stats.py](src/screen_airdrop/receiver/runtime/stats.py)：新增统计字段

**效果**：
```bash
# Slot 池满时的行为：
raw_grab_fps=45.0           # Grab 继续工作，不被阻塞
cap_fps=30.0                # 实际入队速率
dropped_slot_starvation=150 # 丢弃的帧数
slot_starvation_events=150  # 饥饿事件次数
starvation_rate=15%         # 饥饿率 = dropped / raw_grab_frames
```

## 测试验证

### 新增测试文件
1. [test_grab_stats_separation.py](tests/unit/test_grab_stats_separation.py)（5 个测试）
   - 验证 `raw_grab_frames` 和 `captured` 分离
   - 验证 `copy_ms` 统计
   - 验证 slot 池满时的统计行为

2. [test_grab_nonblocking.py](tests/unit/test_grab_nonblocking.py)（6 个测试）
   - 验证 slot 饥饿统计
   - 验证非阻塞机制
   - 验证高饥饿率场景

### 测试结果
- ✅ 所有新增测试通过（11/11）
- ✅ 所有相关测试通过（20/20）
- ✅ Pyright 类型检查通过（0 errors）

## 诊断指标

### 核心指标

| 指标 | 含义 | 计算方式 |
|------|------|----------|
| `raw_grab_frames` | 真实抓屏次数 | grab 线程实际调用 `mss.grab()` 的次数 |
| `captured` | 成功入队次数 | 成功分配到 slot 的帧数 |
| `raw_grab_fps` | 真实抓屏速率 | `Δraw_grab_frames / Δtime` |
| `cap_fps` | 成功入队速率 | `Δcaptured / Δtime` |
| `dropped_slot_starvation` | 饥饿丢帧数 | `raw_grab_frames - captured` |
| `starvation_rate` | 饥饿率 | `dropped_slot_starvation / raw_grab_frames` |

### 诊断流程

```
1. 检查 raw_grab_fps 和 cap_fps
   ├─ 相同 → 无反压，继续检查 grab_ms
   │  ├─ grab_ms 高 → MSS 本身慢（问题根源）
   │  └─ grab_ms 正常 → 系统正常
   └─ 不同 → 有反压，检查 starvation_rate
      ├─ starvation_rate 高 → Slot 池太小或下游太慢
      │  ├─ prep_backlog 高 → Prep 慢
      │  ├─ decode_q 高 → Decode 慢
      │  └─ overwrite 高 → Slot 回收慢
      └─ starvation_rate 低 → 偶发反压，可接受

2. 检查 copy_ms
   ├─ copy_ms 高 → BGR 转换慢（可能是大分辨率）
   └─ copy_ms 正常 → 转换开销可接受

3. 检查 prep_fps 和 accepted_fps
   ├─ prep_fps < raw_grab_fps → Prep 跟不上
   └─ accepted_fps < prep_fps → 大量重复帧被过滤
```

## 性能对比

### 优化前
```bash
# Slot 池满时
cap_fps=30.0                # 被反压限制
raw_grab_fps=30.0           # 和 cap_fps 相同（误导）
grab_ms=15.0                # 实际很快
copy_ms=0.0                 # 未统计（误导）
prep_backlog=5              # 有积压

→ 无法判断是 MSS 慢还是反压
```

### 优化后
```bash
# Slot 池满时
raw_grab_fps=45.0           # 真实抓屏速率（不受反压影响）
cap_fps=30.0                # 实际入队速率
grab_ms=15.0                # 每次 grab 很快
copy_ms=5.0                 # BGR 转换时间
prep_backlog=5              # 有积压
dropped_slot_starvation=150 # 丢弃的帧数
starvation_rate=15%         # 饥饿率

→ 清晰判断：MSS 很快，但被下游反压限制
```

## 向后兼容性

- ✅ 所有现有字段保持不变
- ✅ 新增字段有默认值，不破坏现有代码
- ✅ 统计快照格式不变
- ✅ 进度报告格式不变
- ✅ 现有测试全部通过

## 后续优化（可选）

### P2: 主动 Slot 回收
如果需要更激进的优化，可以实现：
- Coordinator 主动回收最旧的 pending slot
- 类似旧版的 drop-oldest 策略
- 进一步降低 starvation_rate

### P3: 动态调整
- 根据 starvation_rate 自动调整 slot 池大小
- 根据 prep_backlog 动态调整 capture_fps
- 自适应反压控制

## 文档

- [grab_stats_separation.md](docs/grab_stats_separation.md)：详细设计文档
- [test_grab_stats_separation.py](tests/unit/test_grab_stats_separation.py)：统计分离测试
- [test_grab_nonblocking.py](tests/unit/test_grab_nonblocking.py)：非阻塞机制测试

## 总结

通过 P0 和 P1 优化，我们实现了：

1. **清晰的性能诊断**：可以准确区分 MSS 性能问题和反压问题
2. **非阻塞 Grab**：grab 不再被 slot 池阻塞，保持高 `raw_grab_fps`
3. **完整的统计**：恢复 `copy_ms`，新增 `starvation` 指标
4. **向后兼容**：不破坏现有代码和测试

现在可以通过观察 `raw_grab_fps` vs `cap_fps` 的差异，准确判断性能瓶颈的真实原因。
