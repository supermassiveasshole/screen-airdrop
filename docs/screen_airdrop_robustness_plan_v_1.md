# Screen-Airdrop 鲁棒性增强方案（v1）

## 1. 背景与当前结论

当前系统已验证如下事实：

1. `sender` 生成的原始帧本身没有明显问题。
2. 真正导致失败的是 **真实显示 / 采集链路**（显示、远程桌面、压缩、模糊、采样、亮度映射等）把少数帧推到了判决临界点之外。
3. 这些临界帧有时先坏 `header`，表现为 `bad magic`；有时先坏 `payload`，表现为 `payload crc mismatch`。
4. 对同一个 chunk 引入 **mask divergence** 后，跨 epoch 的视觉 realization 不同，多个 epoch 后可成功传输，说明失败具有 **realization / pattern 依赖**。
5. 现阶段 `gray4` 判决主要还是 **固定区间阈值**，这是当前最可疑的脆弱点之一。
6. 仅靠 ECC 无法稳定救回，说明当前错误模式不是“少量随机 bit 错”，而更像：
   - 成簇 / 成片的 symbol error
   - 或某些帧整体灰度分布被压缩后跨阈值错判
   - 或 header 先失锁导致后续无入口

**结论：**
当前问题更像 **信道裕量不足 + 判决边界过脆**，不是 sender correctness 问题，也不是简单堆更强 ECC 能解决的问题。

---

## 2. 目标

本方案目标不是追求“无限堆 epoch”，而是在**少量 epoch / 少量重复**前提下，显著提升以下能力：

1. 提升 `header` 的首帧可读率，减少 `bad magic`。
2. 提升 `gray4 payload` 的判决稳定性，减少 `payload crc mismatch`。
3. 降低系统对单一视觉 realization 的敏感性。
4. 在不引入大规模 ML 依赖的前提下，优先通过协议与接收机自适应提升鲁棒性。
5. 为后续必要时引入 ML 留出清晰接口，但不默认把 ML 当主方案。

---

## 3. 设计总原则

### 3.1 不再把问题视为“码不够强”
当前核心问题不是 FEC 强度不足，而是 **pre-FEC symbol error rate 太高**，并且错误高度相关。

### 3.2 优先降低 raw 判决错误，再让 ECC 工作
正确顺序应为：

1. 降低前端误判率
2. 把局部灾难打散成可管理错误 / erasure
3. 让 ECC/OGRB 处理剩余稀疏错误

### 3.3 区分 header 与 payload
`header` 与 `payload` 的失败机制不完全相同，应分别设计：

- `header`：优先追求“先活下来”
- `payload`：优先追求 gray4 稳定判决 + 可纠错

### 3.4 少量分集优于大量 epoch
既然已验证 `mask divergence` 有效，则更合理的方向是：

- 对同一 chunk 做 **2~3 个不同 realization**
- 而不是大量重复相同 realization

---

## 4. 总体方案结构

本方案分为五层：

1. **Header 鲁棒层**
2. **Gray4 自适应判决层**
3. **Pilot / Calibration 层**
4. **Diversity / Whitening / Interleaving 层**
5. **可选 ML 增强层**

推荐优先级：

- P0：Pilot + adaptive thresholds + confidence/erasure
- P1：Header 分层与增强
- P2：Payload whitening + interleaving + 少量 mask diversity
- P3：必要时引入小型 ML classifier

---

## 5. Header 鲁棒性方案

### 5.1 目标
减少以下问题：

- `bad magic`
- header 首先失锁导致整帧不可用

### 5.2 原则
Header 不应被当作普通高密度数据区处理，而应被视为 **低速控制信道**。

### 5.3 具体方案

#### 5.3.1 Header 与 payload 分离判决
Header 与 payload 分开估计和判决，不共享同一套灰度阈值。

#### 5.3.2 Header 优先 binary 化（推荐）
将 header 从 gray4 降级为更稳的 binary 或更宽松的符号集。

推荐：
- `header = binary`
- `payload = gray4`

这样做的好处：
- 模糊下类间间隔更大
- 更抗亮度压缩
- `magic` 路径更稳

#### 5.3.3 Header 模块尺寸放大
Header 的 module size 设计为 payload 的 `1.5x ~ 2x`，降低模糊、压缩、采样偏差造成的误判。

#### 5.3.4 Header 重复发送
同一帧内可做空间重复，或同一 superframe 内做时间重复。

建议最小策略：
- 同一帧中重复短 header 2 次
- 或 2~3 帧内重复 coarse header

#### 5.3.5 粗头 / 细头分层
将 header 分成两层：

**Coarse Header**（必须稳）：
- sync / magic
- version
- channel id / short mode id
- short seq / short group hint
- header checksum

**Fine Header**（可选补充）：
- full seq
- group id
- shard index
- payload length
- fec mode / flags

目标：即使细头失败，也尽量先让接收端建立最小可用帧身份。

#### 5.3.6 Header guard band
在 header 与 payload 之间增加隔离带，减少 payload 高频边界对 header 的串扰。

---

## 6. Gray4 自适应判决方案（核心）

### 6.1 问题
当前 gray4 主要使用固定区间阈值。这在真实链路下非常脆弱，因为：

- 整体亮度会漂移
- 对比度会压缩
- 局部区域会有亮度偏置
- blur 会把 level 拉向中间
- 不同环境会有明显 distribution shift

### 6.2 目标
把判决从：

`固定阈值 hard decision`

升级为：

`per-frame / per-region adaptive decision + confidence`

### 6.3 自适应判决策略

#### 6.3.1 Per-frame 四级中心估计
对当前帧的 payload modules 灰度样本估计 4 个 gray level center。

推荐方法（从简单到复杂）：
1. histogram valley split
2. k-means / 1D clustering (`k=4`)
3. 基于 pilot 的 level fitting

#### 6.3.2 局部校正
如果发现帧内存在空间不均匀：
- 边缘更暗
- 中心更亮
- 某一侧更模糊

则应：
- 将帧划分为多个 tile / quadrant
- 对每个区域做局部亮度偏移修正
- 或建立低阶亮度场模型后再判决

#### 6.3.3 置信度输出
每个 symbol 判决不仅输出类别，还输出 confidence，例如：
- 到最近 level center 的距离
- 与第二近 center 的 margin

用途：
- 低置信 symbol 标为 erasure
- 为 OGRB / ECC 提供更好的输入

#### 6.3.4 非均匀 gray4 spacing（可选）
发送端 gray4 levels 不必等距。

如果实测发现某些 level 容易混淆，可改为非均匀 spacing，例如：
- 为最容易混淆的相邻级留更大间隔

注意：具体 level spacing 必须基于 confusion matrix 与实测 histogram 选取，不应拍脑袋固定。

---

## 7. Pilot / Calibration 方案（强烈推荐）

### 7.1 目标
通过已知参考块，让接收端在每帧或每组帧中估计当前信道映射，而不是假设 sender 的灰度级会被原样保留。

### 7.2 Pilot 内容
建议每帧放置已知 pilot：
- `P0`：gray level 0
- `P1`：gray level 1
- `P2`：gray level 2
- `P3`：gray level 3

### 7.3 Pilot 布局
Pilot 应分散布局：
- 四角
- 边缘中点
- 中心附近

目的：
- 估计全局四级中心
- 估计局部亮度偏移
- 估计局部对比度压缩

### 7.4 Header 与 payload 分开 calibration
推荐：
- Header 区设置自己的 pilot 或 reference
- Payload 区设置自己的 pilot

不要假设两者共享同一亮度映射。

### 7.5 接收端流程
1. 检测 pilot 区
2. 估计当前帧的 4 个 level center
3. 如有必要，拟合局部亮度校正模型
4. 用该校正结果判决 header / payload

---

## 8. Whitening / Scrambling 方案

### 8.1 作用定位
Whitening 不是主治 header 脆弱，也不是主治 gray4 阈值压缩。它主要用于：

- 打散 payload 内容统计
- 降低某些 chunk 天生形成不友好视觉图样的概率
- 降低内容与视觉 realization 的耦合

### 8.2 推荐做法
**只对白化 payload，不对白化 header。**

Header 应保持可解释、低复杂度、稳健。

### 8.3 实现
推荐使用可逆 PRBS / LFSR scrambling：

`payload' = payload XOR PRBS(seed)`

推荐 seed：
- `chunk_id`
- 或 `(group_id, shard_id)`

### 8.4 注意
Whitening 会打散长 run，但也可能引入更多局部高频边界，因此不应把它视为必然正收益。

### 8.5 结论
Whitening 推荐作为 **payload robustness 辅助手段**，与 adaptive thresholds / pilot / interleaving 组合使用。

---

## 9. Interleaving 方案

### 9.1 目标
将空间局部灾难打散为更均匀的错误分布，使 ECC / OGRB 更容易工作。

### 9.2 做法
对 payload symbols 做 block interleaving：
- 避免相邻视觉 modules 对应相邻 payload bytes
- 让局部区域失败不会直接毁掉一个连续 payload 段

### 9.3 适用场景
特别适合：
- 局部模糊
- 边缘采样差
- 某一角压缩更重
- 局部亮度场偏移

---

## 10. 少量 Diversity 方案（替代大量 epoch）

### 10.1 目标
减少对单一 realization 的依赖，不靠大量 epoch，而靠少量分集提高成功率。

### 10.2 现有结论
已验证 `mask divergence` 有效。因此推荐将其制度化为 **有限多样本传输**。

### 10.3 推荐策略
对每个 chunk 不发送大量相同帧，而是发送 `2~3` 个不同 realization：
- `R0`: mask A
- `R1`: mask B
- `R2`: 可选 mask C

### 10.4 接收端策略
- 哪个 realization 先 CRC 过就用哪个
- 如果多个 realization 都部分成功，可基于 confidence 做 symbol 级合并

### 10.5 好处
这本质上是在做时间分集，但时延远低于大量 epoch。

---

## 11. OGRB / ECC 的角色重定义

### 11.1 当前问题
已有结论表明：单靠 ECC 无法稳定救回，说明当前错误模式过重。

### 11.2 正确定位
ECC / OGRB 不应再被视为“主力翻盘手段”，而应被视为：
- 处理剩余稀疏错误
- 处理 erasure
- 处理 interleaving 后的离散错误

### 11.3 推荐方向
1. 优先让前端输出 `confidence` 或 `erasure`
2. 再让 OGRB / ECC 处理这些低置信点

不要把大量自信错判直接交给 ECC。

---

## 12. 可选 ML 增强方案（仅作为后手）

### 12.1 何时才考虑引入 ML
只有在以下条件成立时，才建议引入 ML：

1. `pilot + adaptive threshold + confidence` 已完成
2. header 增强与 payload calibration 已完成
3. whitening / interleaving / 少量 diversity 已完成
4. 仍然存在稳定的感知判别困难

### 12.2 为什么不把 ML 作为主方案
因为本机测试环境与生产环境存在明显 distribution shift：
- 不同显示器
- 不同截图链路
- 不同远程桌面压缩
- 不同 gamma / scaling / sharpening

大模型或端到端方案很容易学到环境风格，而不是普适的视觉信道规律。

### 12.3 允许的 ML 入口
只允许 ML 作为 **可插拔的局部 classifier**，不要接管整个系统。

推荐入口：
1. `header classifier`
2. `gray4 symbol classifier`

### 12.4 Header classifier
输入：
- header module patch / small strip patch

输出：
- bit / symbol
- confidence

用途：
- 减少 `bad magic`
- 让 header 进入 soft/erasure decode

### 12.5 Gray4 symbol classifier
输入：
- 单个 payload module patch
- 或带少量邻域的 patch

输出：
- `0/1/2/3` 概率分布
- confidence

用途：
- 解决固定阈值下的 level collapse
- 降低 `payload crc mismatch`

### 12.6 不推荐的 ML 用法
- 整帧端到端解码
- RL 自动调制作为第一步
- 超分辨率先增强再解码
- 黑盒替代所有传统解码链路

---

## 13. 接收端推荐新流程

### 13.1 旧流程
`capture -> fixed threshold -> hard decode -> crc/ecc`

### 13.2 新流程
`capture`
-> `ROI / geometry`
-> `pilot extraction`
-> `frame-level / region-level calibration`
-> `header decode (separate path)`
-> `payload symbol classification`
-> `confidence / erasure generation`
-> `interleaving inverse + ECC / OGRB`
-> `chunk/group reconstruction`

---

## 14. 实施优先级（建议按阶段推进）

## Phase 0：观测与诊断补全
目标：为后续策略提供可量化依据。

任务：
1. 对 decode 失败帧也输出：
   - assumed mask id
   - header/payload gray stats
   - symbol histogram
   - pattern metrics
   - confidence 分布（后续）
2. 固定 mask 假设下比较坏帧与邻居
3. 统计：
   - header fail vs payload fail 比例
   - 坏帧空间位置分布
   - symbol confusion matrix

交付：
- 一组离线分析脚本
- 一份失败模式报告

## Phase 1：Gray4 自适应判决（最高优先）
目标：先解决固定阈值脆弱问题。

任务：
1. 增加 pilot cells
2. 实现 per-frame level fitting
3. 实现局部亮度校正（至少 quadrant 级）
4. symbol 判决输出 confidence
5. 支持低置信 symbol -> erasure

交付：
- adaptive gray4 decoder
- A/B 测试结果：固定阈值 vs adaptive

## Phase 2：Header 增强
目标：降低 `bad magic`。

任务：
1. header binary 化
2. header 模块加大
3. header 与 payload 分离判决
4. coarse/fine header 分层
5. header 重复 / guard band

交付：
- 新版 frame layout
- `bad magic` 显著下降的数据

## Phase 3：Payload robustness 增强
目标：减少 realization 敏感性。

任务：
1. payload whitening
2. block interleaving
3. 每个 chunk 默认 2 路 mask diversity
4. 可选 3 路 diversity 作为高鲁棒模式

交付：
- 新版 sender scheduling
- 不同 repetition budget 下的成功率曲线

## Phase 4：可选 ML 插件
目标：补最后一公里的感知判别。

前置条件：仅在 Phase 1~3 完成后仍存在顽固误判时执行。

任务：
1. 构建 patch 级训练集
2. 训练 tiny header classifier
3. 训练 tiny gray4 symbol classifier
4. 用 ML 输出替代固定判决器，但保留原协议与后端纠错逻辑

交付：
- 可插拔 classifier 模块
- 线上/offline A/B benchmark

---

## 15. 默认配置建议（供实现参考）

### 15.1 基础配置
- `header`: binary
- `payload`: gray4
- `payload decoding`: adaptive threshold + pilot-based calibration
- `payload whitening`: enabled
- `interleaving`: enabled
- `diversity`: 2 realizations / chunk

### 15.2 高鲁棒配置
- `header`: binary + repeat
- `payload`: gray4 adaptive + local calibration
- `payload whitening`: enabled
- `interleaving`: strong
- `diversity`: 3 realizations / chunk
- `confidence -> erasure`: enabled

---

## 16. 成功判据

以下指标用于评估方案是否有效：

1. `bad magic` 比例显著下降
2. `payload crc mismatch` 比例显著下降
3. 固定坏 chunk 在少量 diversity 下成功率上升
4. 平均所需 epoch 数显著下降
5. 在不同环境下性能退化可控，而不是单环境过拟合

建议至少报告：
- 单 epoch 成功率
- 2-way / 3-way diversity 成功率
- header fail 比例
- payload fail 比例
- 平均重传轮数
- 端到端有效吞吐

---

## 17. 最终结论

当前系统的主要问题不是 sender correctness，也不是单纯 ECC 强度不足，而是：

- 少数帧在真实显示/采集链路后被推到判决临界点外
- `gray4` 固定区间判决过脆
- header 与 payload 的失效机制不同但都受信道裕量影响

因此，最合理的路线不是直接把希望押在 ML 上，而是按以下顺序推进：

1. `pilot + adaptive thresholds + confidence/erasure`
2. `header binary 化 + 分层增强`
3. `payload whitening + interleaving + 少量 mask diversity`
4. 仅在前述措施后仍存在顽固误判时，引入小型 ML classifier 作为局部增强

这条路线更工程、更可控、更抗 distribution shift，也更适合作为当前 Screen-Airdrop 的下一阶段正式实现方案。

