# Screen-Airdrop 信息密度实验 - 阶段性执行计划

> **文档定位**：本文档是 **Phase 0-5 的阶段性执行计划和任务清单**。
>
> **当前状态（已更新）**：
> - `Phase 0` 已完成：协议接口解耦已落地
> - `Phase 1` 已完成：`compact` 已实现，并完成 synthetic / real-frame / local-screen 三层 benchmark
> - **下一阶段**：进入 `Phase 2 (gray4)` 设计与原型验证
>
> **总纲文档**：完整技术方案、设计哲学、接口规范、理论基础见 [`throughput_optimization_plan.md`](./throughput_optimization_plan.md)

---

## 目的

本分支 `feature/information-density-experiments` 的目标不是替换 `basic` 主线，而是建立一个**可控的协议实验框架**，分阶段验证下面这些方向是否能在手动 ROI 场景下带来真实吞吐收益：

1. `compact`：压缩布局开销
2. `gray4`：多灰度调制
3. `layered`：header/data 分层编码
4. `erasure`：generation-based 擦除码
5. `fountain`：喷泉码 / rateless 广播

当前已经完成：

1. `Phase 0`: 协议接口解耦
2. `Phase 1`: `compact` 协议原型

下一阶段开工目标：

3. `Phase 2`: `gray4` 多灰度调制原型

并行观察目标：

4. 将 `L` 作为本机 `screen + manual ROI` 链路的正式 benchmark track
   - 不再只把 `L` 当作附带低冗余选项
   - 后续 `gray4` / `layered` 评估也应保留 `L` 对照

不在当前开工阶段内的工作：

- 不做 `pilot-grid`
- 不做自动跟踪状态机重构
- 不做 capture backend 重写
- 不把 `basic` 替换成新默认协议

## 当前事实

基于最近实测，当前系统状态是：

- 手动 ROI 下真实吞吐约 `8-10 KB/s`
- `cap_fps` 常见在 `10-18`
- `grab_ms` 常见在 `50-70ms`
- 当前主要瓶颈是 `capture`，不是 `locator`

这意味着当前优化重点应该是：

1. 提高单帧有效载荷比例
2. 保持 `basic` 解码成功率不被破坏
3. 为后续实验协议提供并存能力

同时，基于最近对截图链路的验证，需要补充一个判断：

- `L` should be treated as a first-class benchmark track for the local screen-capture channel, because heavy frame-internal ECC may no longer be the right default assumption.

## 设计原则

1. `basic` 是稳定协议
   - 现有 sender/receiver/test 必须继续可用
   - 行为不因为实验协议而变化

2. 实验协议必须并存
   - `basic`
   - `compact`
   - 后续必须支持 `gray4` / `layered`
   - 上层编码实验必须支持 `erasure` / `fountain`

3. 每一步都可回退
   - 任一阶段收益不成立，不进入主线

4. 先验证吞吐，再谈优雅
   - 优先真实 `KB/s`
   - 其次 CPU/延迟
   - 最后才是代码外观

5. 调制路径和帧内保护路径并行，不互相替代
   - 调制路径：
     - `compact`
     - `gray4`
     - `layered`
   - 帧内保护路径：
     - 重新评估 `L / M / Q / H`
     - 弱化重 repetition ECC 的默认地位
     - 将主要恢复职责逐步上移到 `erasure` / `fountain`
   - 这两条路径不冲突，也不是二选一

## 当前阶段范围

### Phase 0: 协议接口解耦

目标：让 `basic` 和未来实验协议可以通过统一接口接入 sender/receiver，而不是继续把布局、采样、解码逻辑硬编码在单一实现里。

本阶段不要求：

- 大规模目录搬迁
- 重写 `basic` 逻辑
- 修改物理层行为

本阶段要求：

1. 定义最小协议接口
   - `LayoutInfo`
   - `ProtocolEncoder`
   - `ProtocolDecoder`

2. 给 `basic` 加适配层
   - 保持现有行为不变
   - 仅通过接口包装现有实现

3. sender/controller 改为通过协议对象生成帧

4. receiver/pipeline 改为通过协议对象解码帧

5. 所有现有测试继续通过

### Phase 1: `compact` 协议原型

目标：验证“压缩布局开销”这件事是否真的能换来吞吐收益。

候选改动：

- `quiet`: `4 -> 2`
- `finder`: `9x9 -> 7x7`
- `guard`: `2 -> 1`
- 用释放出来的面积扩大 data grid

本阶段不要求：

- 改 ECC
- 改 modulation
- 改 tracking

本阶段要求：

1. `compact` 必须作为独立协议实现存在
2. `basic` 行为不得改变
3. `compact` 至少在 loopback / replay 下可稳定解码
4. 必须给出相对 `basic` 的真实对比数据

## 分支级承诺范围

这个分支的中期目标不是只做到 `compact`，而是按顺序继续验证：

1. `compact`
2. `gray4`
3. `layered`
4. `erasure`
5. `fountain`

顺序不能随意打乱，原因：

- `gray4` 和 `layered` 解决的是**单帧物理层容量**
- `erasure` 和 `fountain` 解决的是**跨帧恢复和广播效率**
- 如果底层单帧实验还没收敛，直接上喷泉码只会把变量混在一起

所以这里的原则是：

1. 先把单帧容量问题看清楚
2. 再把跨帧恢复策略做强

## 已完成阶段

### Phase 0: 已完成

完成内容：

1. 引入最小协议接口：
   - `LayoutInfo`
   - `ProtocolEncoder`
   - `ProtocolDecoder`
2. `basic` 通过协议接口工作
3. sender / receiver / pipeline 已接协议接口
4. 基础回归继续通过

### Phase 1: 已完成

完成内容：

1. `compact` 独立协议实现已存在
2. `compact` 已通过：
   - synthetic roundtrip
   - 真实 `debug/compact` / `debug/compact_v4` 数据集
   - local-screen benchmark
3. benchmark 口径已拆分为：
   - `Synthetic CPU`
   - `Real-frame decode`
   - `End-to-end replay / screen`
4. 已新增 `footprint_matched` benchmark 模式
   - `basic`: `160x96`
   - `compact`: `166x102`
5. 当前真实本机 `screen + manual ROI + 30s` 结果表明：
   - `basic`: `536 B/frame`
   - `compact`: `594 B/frame`
   - `compact` 稳态接收速率约高 `14%~15%`

## 下一阶段：Phase 2 (`gray4`)

当前不再需要继续证明 `compact` 是否成立。  
下一阶段的目标是回答：

1. 在手动 ROI / 本机 screen 场景下，`4-level grayscale` 是否能带来真实吞吐提升？
2. 它的误码上升是否会抵消理论容量提升？
3. `gray4` 应该直接叠到 `compact` 上，还是先做独立原型？
4. 在 `gray4` 演进过程中，`L` 是否仍然比重 frame-internal ECC 更适合作为默认 benchmark 工作点？

### Phase 2 最小目标

1. 新增 `gray4` 协议原型
2. 先保持 finder / timing / locator 主体不变
3. 只修改：
   - payload 区调制方式
   - decoder 的 symbol slicing
   - 必要的 pilot / calibration
4. benchmark 必须沿用当前三层体系
5. 与 `compact` 做同口径比较

### Phase 2 验收标准

1. synthetic roundtrip 可通过
2. replay benchmark 至少不比 `compact` 差
3. local-screen benchmark 在同口径下有明确收益，否则不进入下一阶段
4. `L` 与 `Q` 至少保留并列 benchmark 结果，避免只在高 repetition 假设下评估新协议

## 第一周任务清单（历史记录：Phase 0）

### Task 1: 建协议接口文件

建议文件：

- `src/screen_airdrop/common/protocol_interface.py`

建议内容：

- `LayoutInfo`
- `ProtocolEncoder`
- `ProtocolDecoder`

要求：

- 接口只定义当前真正需要的方法
- 不预先为未来需求过度设计

### Task 2: 给 `basic` 建适配层

建议方式：

- 保留 `encoder_basic.py`
- 保留 `decoder_basic.py`
- 新增一个薄封装，把它们挂到统一接口下

要求：

- 尽量少改现有 `basic` 算法
- 避免第一步就做大搬家

### Task 3: sender 接协议接口

修改点：

- `src/screen_airdrop/sender/controller.py`

要求：

- 通过协议对象获取 layout/capacity
- 通过协议对象编码 frame
- 默认协议仍然是 `basic`

### Task 4: receiver 接协议接口

修改点：

- `src/screen_airdrop/receiver/cli.py`
- `src/screen_airdrop/receiver/pipeline.py`

要求：

- 通过协议对象解码
- 保持现有 `basic` 行为
- 先不引入新 tracker 逻辑

### Task 5: 回归验证

必须跑：

```bash
uv run python -m pytest tests -q
```

可选补充：

```bash
uv run python bench/compare_end_to_end.py --mode replay --protocol all --ecc Q --payload-mode fixed --payload-size 500
```

验收标准：

- 测试全绿
- `basic` 吞吐无明显回退
- 没有新增 CLI 不兼容

**Phase 0 完成标准**：
- ✅ `basic` 能通过接口工作
- ✅ 所有测试通过
- ✅ **没有创建新目录结构**（不做 `src/screen_airdrop/protocols/` 等大搬迁）
- ✅ `BroadcastScheduler` / `BroadcastAssembler` 只做命名占位（可选，可推迟到 Phase 4）

---

## 关键约束（防止 Phase 0 过度设计）

### 不要做的事

1. **不要创建新目录结构**
   - 不创建 `src/screen_airdrop/protocols/`
   - 不创建 `src/screen_airdrop/broadcast/`
   - 保持现有文件组织

2. **不要实现所有具体类**
   - 不实现 `SequentialScheduler` / `ErasureScheduler` / `FountainScheduler`
   - 不实现 `SequentialAssembler` / `ErasureAssembler` / `FountainAssembler`
   - 这些是 Phase 4/5 的工作

3. **不要重写 `basic` 逻辑**
   - 保持 `encoder_basic.py` / `decoder_basic.py` 现有实现
   - 只加薄封装层，不改算法

4. **不要修改物理层行为**
   - 不改变 `basic` 的定位算法
   - 不改变 `basic` 的解码算法
   - 不引入新的 tracker 逻辑

### 要做的事

1. **定义最小接口**
   - `LayoutInfo` - 布局信息
   - `ProtocolEncoder` - 单帧编码
   - `ProtocolDecoder` - 单帧解码

2. **给 `basic` 加适配层**
   - 让 `basic` 能通过接口工作
   - 保持行为不变

3. **修改 sender/receiver 接入点**
   - `controller.py` 通过接口编码
   - `pipeline.py` 通过接口解码
   - 默认协议仍是 `basic`

---
- 没有新增 CLI 不兼容

## 第二周任务清单

仅在 `Phase 0` 稳定后开始。

### Task 6: 建 `compact` 协议原型

建议文件：

- `src/screen_airdrop/protocols/compact/encoder.py`
- `src/screen_airdrop/protocols/compact/decoder.py`

如果当前目录结构不想一次性重构，可以先放在：

- `src/screen_airdrop/sender/encoder_compact.py`
- `src/screen_airdrop/receiver/decoder_compact.py`

但要保证仍走统一协议接口。

### Task 7: 加最小测试

至少补这三类：

1. unit
   - layout capacity
   - header/payload roundtrip

2. integration
   - replay loopback

3. benchmark
   - 与 `basic` 对比有效 `KB/s`

### Task 8: 做第一轮选型结论

如果出现以下任一情况，`compact` 暂不继续：

- 解码成功率明显下降
- 吞吐没有真实提升
- CPU/延迟显著恶化

如果满足：

- 成功率可接受
- 吞吐有稳定提升

再进入下一阶段（`gray4` 或 `layered`）。

## 后续阶段预告

这些不是当前周任务，但属于本分支明确要尝试的内容。

### Phase 2: `gray4`

目标：

- 验证多灰度调制在 loopback / replay / 真实远程桌面下的可用性

关注点：

- 有效容量是否明显提高
- 误码率是否高到抵消收益
- 是否需要退到 `3-gray`

### Phase 3: `layered`

目标：

- 验证 header/data 分层是否能在不显著增加解码复杂度的前提下提高有效容量和鲁棒性

关注点：

- header 强鲁棒区是否值得占用固定面积
- payload 低 ECC 是否真的提高整体好包率

### Phase 4: `erasure`

目标：

- 在线性 chunk 广播模型上先验证 generation-based 擦除码

建议方向：

- `K` 个原始块 + `R` 个冗余块
- receiver 收到任意 `K` 个即可恢复 generation

意义：

- 降低“缺少单个 chunk 必须等整轮重播”的等待
- 为后续多发送区并行做准备

### Phase 5: `fountain`

目标：

- 验证喷泉码是否能在多发送区并行和中途加入场景下优于固定率擦除码

前提：

- `erasure` 已经完成
- generation/symbol 抽象已经稳定

意义：

- 支持更灵活的持续广播
- 更适合多发送区无严格协调的并行发射

## 明确暂缓项

这些方向有价值，但不属于当前开工范围：

1. `gray4`
   - 本分支会做，但不是现在立刻开工

2. `layered`
   - 本分支会做，但在 `gray4` 之后再做

3. `pilot-grid`
   - 不属于当前分支的承诺目标

4. 自动跟踪重构
   - 当前以手动 ROI 为主，不优先

5. 喷泉码 / 擦除码
   - 本分支明确会做，但必须排在单帧实验之后

## 成功标准

当前分支的短期成功，不是“做出很多协议”，而是做到下面三件事：

1. `basic` 主线稳定不退化
2. 新协议实验可以低成本接入
3. `compact` 能给出一份可信的收益/失败结论

当前分支的中期成功，是：

4. `gray4` 和 `layered` 至少有一个给出正收益结论
5. `erasure` 相对纯重复广播有明确恢复效率收益
6. `fountain` 至少完成原型验证，而不是停留在设想层

## 失败标准

出现以下任一情况，应立即停止继续扩展协议数量，先收敛：

1. `Phase 0` 之后测试不稳定
2. `basic` 行为开始漂移
3. `compact` 还没验证完，就开始并行做 `gray4`/`pilot`
4. 无 benchmark 数据就推进主线合并
5. 在 `compact/gray4/layered` 还没收敛时就并行推进喷泉码

## 当前建议执行顺序

1. 做 `Phase 0`
2. 跑完整测试
3. 补最小 benchmark
4. 做 `compact`
5. 出第一轮对比报告

只要前四步没完成，不进入 `gray4`。

---

## 文档关系说明

### 本文档定位

本文档是 **阶段性执行计划**，提供：

1. **当前事实和设计原则**
   - 基于 2026-03-07 实测的性能基线
   - 明确的"做什么"和"不做什么"

2. **Phase 0-5 的任务清单**
   - 每个 Phase 的具体任务分解
   - 验收标准和失败标准
   - 执行顺序和依赖关系

3. **成功/失败标准**
   - 短期成功：架构解耦 + compact 验证
   - 中期成功：单帧优化 + 跨帧优化
   - 失败标准：何时停止扩展

### 与总纲文档的关系

```
throughput_optimization_plan.md (总纲)
├─ WHY: 为什么要做这些优化（设计哲学、理论基础）
├─ WHAT: 做什么（5 个实验协议的设计细节）
└─ HOW (设计层): 怎么设计（接口规范、架构解耦）

information_density_kickoff.md (本文档)
├─ HOW (执行层): 怎么执行（任务清单、步骤分解）
├─ WHEN: 什么时候做（执行顺序、依赖关系）
└─ DONE: 如何验收（成功标准、失败标准）
```

**使用建议**：
- 理解整体方向和技术决策 → 读总纲文档
- 立即开工执行、跟踪进度 → 读本文档
- 查看接口定义和代码示例 → 读总纲文档
- 确认任务是否完成 → 读本文档的验收标准
