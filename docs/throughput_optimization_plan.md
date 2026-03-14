# Screen-Airdrop 吞吐提升方案

## 1. 文档定位

本文档是总纲，不是施工单。

它回答五个问题：

1. 我们现在到底在优化什么。
2. 当前已经得到哪些结论。
3. 后续协议演进应遵循什么分层原则。
4. 各阶段分别解决什么问题。
5. 当前最值得推进的下一步是什么。

具体开工任务和周计划见：
- [information_density_kickoff.md](./information_density_kickoff.md)

单帧效率理论分析见：
- [protocol_efficiency_report.md](./protocol_efficiency_report.md)

benchmark 现状和结果见：
- [benchmark_status.md](./benchmark_status.md)
- [frame_decode_success_status.md](./frame_decode_success_status.md)

### 1.1 规范性说明

从本节以下开始，本文档后半部分同时承担**规格说明书**作用。

为减少实现歧义，使用以下术语：

- **MUST**：实现必须满足
- **SHOULD**：默认推荐满足；若不满足，需要明确说明理由
- **MAY**：可选实现

如果本文档与阶段性讨论记录冲突，以本文档当前版本为准。

---

## 2. 核心问题

当前系统仍然更接近“动态二维码”思路：

- 一帧 = 一个完整数据包
- 丢一帧 = 等下一轮 epoch
- 每帧都要定位、采样、解码、再进入组包

这条路线的问题不是“完全不能用”，而是上限不高：

1. 单帧开销大
   - finder
   - quiet zone
   - guard
   - timing
   - header / format

2. 当前帧内 ECC 很重
   - `L/M/Q/H` 当前对应 `1x/2x/3x/4x repetition`
   - 在 `Q/H` 档损耗尤其明显

3. 恢复职责主要还在单帧层
   - 丢 chunk 仍然偏依赖回绕
   - 中途加入和跨帧恢复能力不足

所以后续演进目标不是把单帧继续做成“更完美的小二维码”，而是：

> 让每一帧成为高效、可判定、可被上层恢复层利用的 symbol carrier。

也就是从“逐帧图片协议”转向“视觉物理层 + 轻量链路层”。

---

## 3. 当前已确认的事实

### 3.1 已完成阶段

1. `Phase 0` 已完成
   - 协议接口解耦已经落地
   - `basic` 已通过统一接口工作

2. `Phase 1` 已完成
   - `compact` 已落地
   - `compact` 已通过三层 benchmark：
     - `Synthetic CPU`
     - `Real-frame decode`
     - `End-to-end replay / local-screen`

### 3.2 当前 benchmark 结论

在 `footprint-matched` 口径下：

- `basic`: `160x96`, `536 B/frame`
- `compact`: `166x102`, `594 B/frame`

在真实本机 `screen + manual ROI + 30s` benchmark 中：

- `compact` 相比 `basic`
  - 单帧 payload 提升约 `10.8%`
  - 稳态接收速率提升约 `14%~15%`

另外，当前还确认了一个更激进但重要的工作点：

- `--protocol compact --module-grid 224x136 --ecc-level L --fps 12 --chunk-size 3387`

在当前本机截图测试环境里，该配置已经可以稳定运行，并且**发送端口径**下可达到约：

- `40 KB/s`

这条结果的意义是：

1. 当前截图链路对 `L` 的容忍度明显高于最初假设
2. `L` 不再只是理论上可以讨论的低冗余档位，而是已经进入真实可运行区间
3. 后续单帧优化和 `gray4` 评估，不应只默认围绕 `Q/H` 展开

结论：

- `compact` 已经成立
- 当前主问题不再是“是否继续证明 compact 有价值”
- 下一阶段应该继续寻找单帧净信息密度的上升空间
- 并且 `L` 已经进入真实高吞吐工作点范围，应继续作为正式 benchmark track 保留

### 3.3 当前链路瓶颈

基于最新实测：

- `cap_fps`: 常见 `10-18`
- `grab_ms`: 常见 `50-70ms`
- `locate_ms`: 常见 `20-30ms`
- `decode_ms`: 常见 `10-15ms`

当前更大的系统瓶颈仍然是：

- `capture`

而不是：

- `locator`

这意味着当前优先级不应先放在自动跟踪大重构上，而应优先放在：

1. 单帧净信息密度
2. 单帧 detectability / decode stability
3. 之后再做跨帧恢复优化

---

## 4. 关键设计判断

### 4.1 单帧层与跨帧层职责分离

后续协议演进应明确分成两层：

#### A. 单帧物理层（Phase 1-3）
负责：

- 提升单帧有效信息密度
- 降低静态结构开销
- 提高 frame-level detectability
- 保证 header / control plane 易识别

对应方向：

- `compact`
- `gray4`
- `layered`

单帧物理层内部又可以再拆成四个算法子问题：

1. **几何定位**
   - 识别 frame 是否存在
   - 恢复四角或等价几何约束
   - 估计透视变换

2. **相位与采样**
   - 从 timing rail / pilot 中估计采样相位
   - 决定每个 module 在 warp 后的采样中心
   - 控制插值、邻域投票和阈值稳定性

3. **symbol 判决**
   - `basic/compact`：二值判决
   - `gray4`：4-level slicing
   - 后续 `layered`：header/data 可能采用不同判决策略

4. **frame-level validity**
   - header 是否可信
   - payload 是否可信
   - 该帧应被接收、丢弃，还是上交 outer layer 当作擦除

这四个问题必须分别评估，不能把“定位成功”和“最终有效吞吐”混成一个指标。

#### B. 跨帧恢复层（Phase 4-5）
负责：

- 把缺帧视为擦除
- generation-based 恢复
- rateless / fountain 广播
- 中途加入与持续恢复

对应方向：

- `erasure`
- `fountain`

### 4.2 调制路径与帧内保护路径并行，不冲突

后续优化不是一条线，而是两条并行路径：

#### 路径 1：调制路径
目标：提升单帧净信息密度

- `compact`
- `gray4`
- `layered`

这条路径主要回答：

- 在同样显示面积下，每帧还能装多少净信息
- 在截图链路里，module 能否仍被稳定判决
- 提高 bits/module 后，是否会被定位/采样误差抵消

#### 路径 2：帧内保护路径
目标：降低单帧内部冗余税

- 重新评估 `L / M / Q / H`
- 弱化重 repetition ECC 的默认地位
- 将主要恢复职责逐步上移到 `erasure / fountain`

这条路径主要回答：

- 坏帧是否应该尽早被判为擦除
- 轻量 frame CRC 是否足够
- 当前 frame-internal repetition 是否仍值得保留
- 哪些恢复职责应当由 outer layer 承担，而不是继续堆到单帧里

结论：

- **多灰度** 与 **减少单帧校验/纠错开销** 不是二选一
- 两条路径可以并行评估

### 4.3 `L` 是正式 benchmark track

这是当前最重要的新增判断：

> `L` should be treated as a first-class benchmark track for the local screen-capture channel, because heavy frame-internal ECC may no longer be the right default assumption.

原因：

1. 本机 `screen + manual ROI` 链路比 camera 场景干净得多。
2. 当前理论分析表明，`L` 是现有协议唯一已经接近 QR 单帧密度的档位。
3. 如果 `L` 在真实截图链路里稳定，那么当前默认的重 frame-internal repetition 就不再合理。

这不意味着：

- 直接放弃单帧校验

而是意味着：

- 保留轻量 frame check（如 header CRC / payload CRC）
- 不再默认把重冗余 repetition 当作主要恢复手段
- 逐步把恢复职责上移到 `erasure / fountain`

---

## 5. 为什么当前还打不过大 QR

理论结论已经单独写在：
- [protocol_efficiency_report.md](./protocol_efficiency_report.md)

这里只保留最重要的结论：

1. 当前协议单帧利用率低，不是因为实现“没灌满”
2. 主要损耗来自：
   - repetition ECC
   - 静态结构开销
   - header
   - sender 的 `0.9` safe cap
3. 在 `L` 档，当前协议已经有结构性竞争力
4. 在 `M/Q/H` 档，当前协议与大 QR 的差距仍然明显

这意味着后续单帧优化如果要继续有效，优先级应该是：

1. 继续提升单帧调制效率（`gray4` / `layered`）
2. 重新设计 frame-internal ECC 策略
3. 不再把重 repetition 当作长期默认方案

---

## 6. 架构方向

### 6.1 总体分层

```text
Transmission Layer
  - manifest / packing / restore / assembler

Protocol Interface
  - LayoutInfo
  - ProtocolEncoder
  - ProtocolDecoder

Physical Protocols
  - basic
  - compact
  - gray4
  - layered

Broadcast Coding Layer
  - sequential
  - erasure
  - fountain
```

### 6.2 当前架构目标

现阶段不追求一次性重写所有代码，而是保证：

1. `basic` 继续稳定工作
2. 新协议可并存
3. 新协议能通过统一接口进入 sender / receiver / pipeline
4. 后续 `erasure / fountain` 有清晰接入层

### 6.4 接口与职责边界（规范）

为避免后续实现把层次重新耦合，以下边界视为规范：

#### 单帧物理层 MUST

- 接收一帧视觉载体
- 输出：
  - header 是否可信
  - payload 是否可信
  - 若可信，输出 payload symbol
  - 若不可信，输出擦除

单帧物理层 **MUST NOT** 承担：

- 跨 generation 恢复
- 广播调度
- 对文件完成度的全局判断

#### 跨帧恢复层 MUST

- 接收来自单帧层的：
  - systematic symbol
  - coded symbol
  - erasure
- 独立维护 generation 状态
- 决定 generation 何时可恢复、何时完成

跨帧恢复层 **MUST NOT** 依赖：

- 某一特定 frame 必须成功到达
- epoch 边界必须完整可见

#### Header / Payload 分工 MUST 明确

- header 负责控制面信息
- payload 负责数据面信息
- 后续 `layered` 设计 **MUST** 保持这种职责分离，而不是重新混回单一冗余预算

### 6.3 当前不承诺的方向

本分支当前不承诺：

- `pilot-grid`
- 自动跟踪状态机重构
- capture backend 重写

这些方向不是永远不做，而是当前不作为主线路径。

---

## 7. 分阶段路线图

### Phase 0：协议接口解耦
状态：已完成

目标：
- 让 `basic` 通过统一接口工作
- 为实验协议并存提供边界

产出：
- `LayoutInfo`
- `ProtocolEncoder`
- `ProtocolDecoder`
- `basic` adapter

### Phase 1：`compact`
状态：已完成

目标：
- 压缩静态结构开销
- 验证更紧凑布局是否带来真实收益

当前结论：
- 成立
- 已在真实本机 benchmark 中优于 `basic`

### Phase 2：`gray4`
状态：下一阶段

要回答的问题：

1. `4-level grayscale` 是否能在本机截图链路里带来真实吞吐提升？
2. 它的误码上升是否会抵消理论容量收益？
3. `gray4` 更适合：
   - 直接叠到 `compact`
   - 还是先做独立原型？
4. 在 `gray4` 评估过程中，`L` 是否仍然是更合理的 benchmark 工作点？

约束：

- finder / timing / locator 主体尽量不变
- 只优先改：
  - payload 调制
  - symbol slicing
  - 必要的 calibration / pilot

核心算法重点：

1. **数据区从 binary 改为 4-level symbol**
   - 每个 payload module 承载 `2 bits`
   - finder / timing / control plane 初期仍保持二值

2. **引入局部灰度校准**
   - 不能依赖固定阈值
   - 需要利用 pilot / reference cells 估计：
     - 黑场
     - 白场
     - 中间两档灰度中心

3. **decoder 需要做 slicing，而不是简单 threshold**
   - 输入是 module 的局部亮度统计
   - 输出是 `0/1/2/3`
   - 同时给出置信度，便于后续 outer layer 或 layered 设计使用

4. **gray4 的 benchmark 不能只看理论 2x**
   - 必须同时观察：
     - frame success rate
     - bad frame rate
     - locator fail rate
     - goodput

推荐的最小实现顺序：

1. 保持 finder / timing / header 二值不动
2. 只让 payload 区进入 4-level 调制
3. 先做全局 slicing
4. 再做基于 pilot 的局部 slicing
5. 最后再决定是否值得与 `L` / `Q` 不同 ECC 工作点组合

#### `gray4` 规格边界

`gray4` 第一版实现 **MUST** 满足：

1. finder / timing / header 区域保持二值
2. 只有 payload 区进入 4-level 调制
3. decoder 输出的 symbol 既包含：
   - 判决值
   - 也包含置信度或等价质量指标
4. benchmark 结果必须至少同时给出：
   - frame success rate
   - bad frame rate
   - locator fail rate
   - goodput

`gray4` 第一版实现 **SHOULD NOT** 同时引入：

- header/data 分层重写
- 新 tracker
- 新 capture backend

否则无法判断收益来源。

验收标准：

1. synthetic roundtrip 通过
2. replay benchmark 至少不比 `compact` 差
3. local-screen benchmark 有明确收益
4. `L` 与 `Q` 至少保留并列 benchmark 结果

### Phase 3：`layered`
状态：待开始

目标：
- 分离 header / payload 保护强度
- 让 control plane 更稳、data plane 更激进

预期价值：
- header 保持高鲁棒
- payload 提升密度
- 为后续 outer code 做准备

`layered` 不是简单把 frame 分成“上半区和下半区”，而是要明确分离 **control plane** 与 **data plane** 的职责。

建议的算法理解方式：

1. **control plane**
   - frame_id
   - session_id
   - generation_id
   - symbol type
   - mode / layout 信息

   要求：
   - 高鲁棒
   - 易判决
   - 允许较低容量

2. **data plane**
   - 真正的 payload symbols

   要求：
   - 更高密度
   - 允许更高误码率
   - 失败时优先上交 outer layer 当作擦除

从算法上讲，`layered` 的关键不是“再加更多结构”，而是：

- header 区可以保守
- data 区可以激进
- 让两者不再共享同一套冗余预算

#### `layered` 规格边界

`layered` 实现 **MUST** 明确输出两套独立设计决策：

1. control plane 的：
   - 调制方式
   - 冗余策略
   - 判决准则

2. data plane 的：
   - 调制方式
   - 冗余策略
   - 失败处理方式

`layered` 的目标不是“再提高整体复杂度”，而是：

- 把控制面做得更稳
- 把数据面做得更激进
- 为 outer layer 擦除恢复创造更清晰的接口

### Phase 4：`erasure`
状态：待开始

目标：
- generation-based 擦除恢复
- 让坏帧更自然地变成 erasure，而不是等待顺序回绕

### Phase 5：`fountain`
状态：待开始

目标：
- rateless / sliding-window broadcast
- 支持中途加入与持续恢复

### OGRB 设计澄清：Phase 4-5 的默认方向

`erasure` / `fountain` 在本项目里不应理解为“整文件大喷泉”或“固定率顺序冗余”的简单替换。

当前更合理的方向是：

> **OGRB（Overlapping Generation Rateless Broadcast）**
>
> 即：**重叠代际 + 短周期 rateless 广播**

它不是单一固定参数协议，而是一族可调工作点。其目标不是找到一个永远最优的参数组，而是在不同 sender FPS、capture FPS 和丢帧条件下，选择更偏向：

- 恢复成功率
- 重访压力控制
- 最大吞吐

的不同配置。

#### 为什么不是整文件喷泉

整文件喷泉在当前 Screen-Airdrop 场景里并不是第一优先选择，原因是：

1. 解码规模过大
2. 首次可恢复时间偏长
3. 重访周期不可控
4. 调试复杂度过高

因此更适合当前阶段的做法是：

- 小 generation
- 有限重叠
- 少量 systematic 前缀
- 持续 coded symbols
- 短周期交错调度

#### OGRB 的三层结构

##### A. 物理帧层

每帧只负责：

- 携带一个 symbol
- header 可识别
- payload 可信则交付
- 坏帧优先视为擦除并丢弃

##### B. 代际编码层

原始数据切成很多小 generation，每个 generation 独立恢复。

##### C. 广播调度层

决定当前发哪个 generation、发 systematic 还是 coded、如何在新旧 generation 之间分配 airtime。

这三层必须分开思考。否则最终会把“单帧设计”“编码策略”“广播节奏”混成一个无法 benchmark 的整体。

#### OGRB 的最小算法骨架

如果只描述最小可落地版本，OGRB 的 sender/receiver 可以这样理解：

##### Sender 侧

1. 把文件切成固定大小 `source symbols`
2. 按 `generation_size` 组成 generation
3. generation 之间按 `generation_overlap` 产生重叠
4. 每个 generation 先发少量 `systematic_prefix`
5. 之后持续发 coded symbols
6. scheduler 维持有限个 `active generations`
7. 用 `old_new_ratio` 决定 airtime 倾斜给旧代还是新代

##### Receiver 侧

1. 先完成单帧 header 解析
2. 坏 header / 坏 payload 直接当擦除
3. 按 `generation_id` 归档收到的 symbols
4. 对 systematic symbols 直接记账
5. 对 coded symbols 记录 seed / degree / payload
6. 达到 `decode_margin` 条件后尝试恢复
7. 成功则输出该 generation 的原始 symbols

这样做的目的不是“每帧都恢复”，而是：

- 每帧尽量贡献新自由度
- generation 尽快变为可解
- 重访周期保持短

#### OGRB 的默认参数（规范起点）

如果没有特别说明，OGRB 第一版默认参数 **SHOULD** 从下列值起步：

```text
symbol_size = 512 bytes
generation_size = 20~24
generation_overlap = 0.125~0.25
systematic_prefix = 6~8
coded_redundancy = 1.15~1.25
max_active_generations = 2
old_new_ratio = 1.5
decode_margin = 1
```

解释：

- 这是当前默认 `balanced` profile 的实现起点
- `robust` 与 `throughput` 作为 profile 偏移
- 不应在未 benchmark 前直接把极端参数当默认值

#### OGRB Header 字段要求

为避免后续 sender/receiver 实现各自解释，OGRB 帧头 **SHOULD** 至少包含：

- `session_id`
- `generation_id`
- `generation_start`
- `generation_size`
- `symbol_size`
- `symbol_type` (`systematic` / `coded`)
- `symbol_index`（systematic 时有效）
- `coding_seed`（coded 时有效）
- `degree`（coded 时有效）
- `header_crc`
- `payload_crc`

这里的关键要求是：

- generation 归属必须显式可见
- symbol 类型必须显式可见
- header 与 payload 的有效性必须可分离判定

#### OGRB Receiver 状态机（最小规范）

Receiver 对每个 generation **MUST** 至少维护以下状态：

- `known_systematic_symbols`
- `known_coded_symbols`
- `decode_attempted`
- `decode_completed`
- `last_progress_ts`

Receiver **SHOULD** 采用以下解码顺序：

1. 优先轻量恢复（如 peeling / BP）
2. 只有在接近可解但轻量恢复卡住时，再进入更重 fallback

Receiver **MUST NOT** 默认对每个 generation 都立即执行重解码。

#### OGRB 的核心 tradeoff

OGRB 不是简单的“高冗余 vs 低冗余”。它至少有三个独立 tradeoff：

##### 1. 推进速度（forward progress）

决定新数据向前推进有多快。

主要受这些参数影响：

- generation overlap
- max active generations
- old/new airtime ratio

它回答的问题是：

- 新数据多久能进入空口
- sender 是否总在重复救旧数据而不向前走

##### 2. 重访速度（revisit pressure）

决定旧 generation 多快再次拿到有用自由度。

主要受这些参数影响：

- overlap
- old/new ratio
- max active generations
- 调度策略是否偏向旧代

它回答的问题是：

- 如果某个 generation 还差一点，自由度多久能回来一次
- 接收端是否要等很长周期才能再次看到与当前缺口相关的信息

##### 3. 恢复成功率（recovery robustness）

决定 generation 在丢帧环境下能否及时完成恢复。

主要受这些参数影响：

- generation size
- coded redundancy
- systematic prefix
- decode margin

它回答的问题是：

- generation 是否容易在丢帧下被卡住
- 接收端是否需要太多额外 symbols 才能完成恢复

结论：

- OGRB 不能被理解成“环境差就加 overlap，环境好就减 overlap”
- 必须分别权衡推进速度、重访速度和恢复成功率

#### overlap 是昂贵旋钮，不应默认优先拉高

overlap 的确有价值：

- 它能提供第二条恢复路径
- 它能缩短局部重访机会

但它代价很高：

- 直接降低前进速度
- 增加 airtime 重复消耗

因此在高丢帧环境下，默认优先级更合理的顺序通常是：

1. 减小 generation size
2. 提高 coded redundancy
3. 增强旧代偏置（old generation bias）
4. 只有在必要时再提高 overlap

也就是说：

> overlap 应视为昂贵但有效的第二层保护机制，而不是高丢帧场景下默认优先拉高的第一旋钮。

#### `max_active_generations` 的默认判断

当前总纲不建议把 `max_active_generations = 3` 作为默认值。

更合理的默认判断是：

- `1`：吞吐优先场景
- `2`：默认平衡点
- `3`：实验参数，可保留，但不建议作为默认鲁棒性档案

原因：

- 活跃代过多会打散 airtime
- sender FPS 低时，会让每个 generation 都长期半完成
- 当前链路更怕“每个 generation 都推进不起来”，而不是“重访还不够短”

#### 环境分型

OGRB 的默认工作点不应假设所有环境相同。至少要区分三类：

##### 场景 A：远程服务器

特点：

- sender FPS 低
- 丢帧率高
- capture FPS 中等

核心问题：

- 发送慢
- 丢帧高

##### 场景 B：macOS 本地测试

特点：

- sender FPS 较高或足够高
- sender 侧丢帧低
- receiver capture FPS 有限

核心问题：

- receiver 对发送流做的是“稀疏采样”

工程含义：

- 过高 revisit pressure
- 过高 overlap
- 过多重复 coded frames

都可能浪费接收端有限的采样机会。

因此在该场景下，更合理的方向通常是：

- 中等 generation size
- 低到中等 overlap
- 中低冗余
- 较高 systematic prefix

##### 场景 C：理想环境

特点：

- sender FPS 高
- 丢帧低
- capture FPS 也高

核心问题：

- 尽量减少冗余
- 追求最大吞吐

#### 推荐的高层参数模型

不建议一开始只从底层参数角度理解 OGRB。更合理的产品/配置视角是三类高层旋钮：

##### A. Protection Level

映射到：

- generation size
- coded redundancy
- decode margin

##### B. Revisit Pressure

映射到：

- overlap
- old/new airtime ratio
- max active generations

##### C. Startup Bias

映射到：

- systematic prefix

结论：

- 底层实现可以暴露全部参数
- 但 CLI / 文档默认更适合先暴露高层 profile

#### 默认 profile 设计

##### Profile 1：`robust`

适用：

- 远程服务器
- 高丢帧
- 低 sender FPS
- 恢复成功率优先

建议参数范围：

```text
generation_size = 12~16
generation_overlap = 0.25
systematic_prefix = 4
coded_redundancy = 1.4~1.6
max_active_generations = 2
old_new_ratio = 2.0~2.5
decode_margin = 2
```

解释：

- 小 generation：缩短完成时间
- 高 coded redundancy：优先提升恢复成功率
- 强旧代偏置：缩短尾部延迟
- overlap 只取 25%，不默认拉到 50%

算法含义：

- 先保证“这一代能尽快解出来”
- 再考虑是否继续向前推进

##### Profile 2：`balanced`

适用：

- macOS 测试
- 一般本地环境
- capture FPS 有限
- 吞吐与鲁棒性折中

建议参数范围：

```text
generation_size = 20~24
generation_overlap = 0.125~0.25
systematic_prefix = 6~8
coded_redundancy = 1.15~1.25
max_active_generations = 2
old_new_ratio = 1.5
decode_margin = 1
```

解释：

- generation 中等，避免太频繁切代
- overlap 保持低到中等
- systematic 略高，更适合 receiver 稀疏采样
- redundancy 中低，兼顾效率和恢复率

算法含义：

- 让新数据持续前进
- 同时又不给旧代太长尾延迟
- 更适合本机 `screen + limited capture FPS` 的场景

##### Profile 3：`throughput`

适用：

- 理想环境
- sender/capture 都快
- 极低丢帧
- 吞吐优先

建议参数范围：

```text
generation_size = 28~32
generation_overlap = 0
systematic_prefix = 8~12
coded_redundancy = 1.05~1.10
max_active_generations = 1
old_new_ratio = 1.0
decode_margin = 0
```

解释：

- 大 generation：提高净效率
- 无 overlap：最大化前进速度
- 极低冗余：只保留最小保护
- 单活跃代：不分散 airtime

算法含义：

- 牺牲一部分最坏情况恢复体验
- 换取更高 raw throughput 和更高潜在 goodput

#### 关于“效率”口径

不要把 OGRB 的效率理解成单一线性公式，例如：

```text
effective_bandwidth = 1 / (redundancy × (1 + overlap))
```

这种表达最多只能提供直觉，不能代表真实结果。

更合理的指标至少要分成：

##### raw throughput

每秒发出的 payload bytes

##### goodput

每秒真正恢复出的原始有效 bytes

##### completion latency

从开始到完整恢复所需时间

因此：

- overlap 和 redundancy 会降低 raw throughput
- 但在高 loss 下，可能提高 goodput 或降低 completion latency
- OGRB 参数选择必须基于 benchmark，而不是基于单一公式

#### sender 自适应不是当前主线

当前不建议把 sender 侧自适应写成默认主线方案。

原因：

- 当前视觉广播链路通常缺乏可靠反馈信道
- sender 很难天然知道：
  - 实际 loss rate
  - receiver decode progress
  - generation completion 状态

因此当前更合理的是：

- 静态 profile
- 离线 benchmark
- 手动选择工作点

只有在未来引入可靠反向控制信道后，sender 侧自适应调度才更适合作为正式方向。

#### CLI / 配置建议

推荐两层配置方式：

##### 方式 1：profile 级选择（默认推荐）

```bash
--ogrb-profile robust
--ogrb-profile balanced
--ogrb-profile throughput
```

##### 方式 2：高级参数覆盖（实验用）

```bash
--ogrb-generation-size 20
--ogrb-generation-overlap 0.25
--ogrb-systematic-prefix 6
--ogrb-coded-redundancy 1.2
--ogrb-max-active-generations 2
--ogrb-old-new-ratio 1.5
--ogrb-decode-margin 1
```

结论：

- 默认推荐 profile 方式
- 细粒度参数覆盖仅面向实验和 benchmark
- 不建议普通使用路径直接暴露全部参数

#### 实现约束

OGRB 第一版实现 **MUST** 优先支持：

- 静态 profile 选择
- 离线 benchmark
- 手动选择工作点

OGRB 第一版实现 **SHOULD NOT** 依赖：

- sender 侧自适应反馈
- receiver 进度回传
- 动态在线 profile 切换

这些都可以作为未来扩展，但不应成为第一版落地的前提。

#### OGRB 的总结性判断

> OGRB 的目标不是寻找一个固定“最优参数组”，而是提供一族可调工作点：在不同 sender FPS、capture FPS 和丢帧条件下，分别选择更偏向恢复成功率、重访压力控制或最大吞吐的配置。

---

## 8. 当前优先级

如果只问“现在最该做什么”，答案是：

1. 进入 `Phase 2 (gray4)`
2. 同时把 `L` 作为正式 benchmark track 持续保留
3. 不再继续把重 frame-internal repetition 当作默认前提
4. 在单帧层收敛之后，再正式推进 `erasure / fountain`

换句话说，当前最合理的行动顺序是：

- 先继续把单帧物理层做好
- 同时松动单帧重纠错假设
- 最后再把主要恢复能力迁移到跨帧层

---

## 9. 这份文档不回答什么

本文档不回答：

- 具体每周任务怎么排
- 某个脚本怎么运行
- 当前 benchmark 的具体数字明细
- 单帧效率的详细公式推导

这些分别去看：

- [information_density_kickoff.md](./information_density_kickoff.md)
- [benchmark_status.md](./benchmark_status.md)
- [frame_decode_success_status.md](./frame_decode_success_status.md)
- [protocol_efficiency_report.md](./protocol_efficiency_report.md)
