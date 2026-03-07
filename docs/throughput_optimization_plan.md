# Screen-Airdrop 吞吐提升方案（架构重构 + 实验协议）

## 目标

通过**架构解耦 + 实验协议并存**，逐步验证单帧信息密度优化，最终实现 **2-3 倍传输速率提升**。

**核心原则**：
1. **不破坏 `basic` 主线**：保持稳定协议继续工作
2. **先优化单帧容量**：在手动 ROI 场景下验证收益
3. **后优化定位跟踪**：等单帧优化验证后再考虑

## 当前基线（2026-03-07 实测）

### 1. 真实性能数据

```
手动 ROI 模式（最新实测）:
- cap_fps: 10-18 FPS
- rx_KBps: 8-10 KB/s
- grab_ms: 50-70ms (屏幕捕获)
- locate_ms: 20-30ms (定位)
- decode_ms: 10-15ms (解码)
```

**关键发现**：
- **屏幕捕获是主瓶颈**（50-70ms），不是定位（20-30ms）
- 手动 ROI 下定位已经相对轻量
- 当前吞吐 ~8-10 KB/s，远高于之前 benchmark 的 0.5-1 KB/s

### 2. 容量开销分析

当前 `basic` 协议的模块分配：

```
总模块数: 190×126 = 23,940
├─ 有效载荷 (data grid): 160×96 = 15,360 (64.2%)
└─ 协议开销: 8,580 (35.8%)
   ├─ Quiet zone: ~1,500 modules (边缘白边)
   ├─ Finder patterns: 4×(9×9) = 324 modules (四角定位符)
   ├─ Guard band: ~1,024 modules (隔离带)
   └─ Timing patterns: ~512 modules (相位校准)
```

**优化空间**：
- Quiet zone 和 guard band 信息密度为零（可压缩）
- Data grid 只用二值调制（可升级到 4-gray）
- Header 和 data 混在一起（可分层）

### 3. 优化优先级

基于当前基线，优化优先级应该是：

```
优先级 1: 单帧信息密度（+40-60% 容量）
  ├─ 减小 quiet zone / guard band
  ├─ Header/data 分层布局
  └─ 4-gray 调制（2× 容量）

优先级 2: 屏幕捕获优化（-30-50% 延迟）
  ├─ 优化 ROI 裁剪
  ├─ 降低捕获分辨率
  └─ 多线程并行捕获

优先级 3: 定位跟踪优化（-50-70% 定位延迟）
  ├─ 帧间跟踪（复用变换矩阵）
  ├─ 导频符号快速验证
  └─ 自适应回退
```

**结论**：当前不应该先做定位优化，而应该先做**单帧容量优化**。

---

## 架构重构：协议实验能力解耦

### 当前问题

当前代码的协议实现高度耦合：

```
encoder_basic.py
  ├─ 布局计算（quiet/finder/guard/grid）
  ├─ 模块填充（timing patterns）
  ├─ 数据编码（header + payload）
  └─ 渲染输出（OpenCV）

decoder_basic.py
  ├─ 定位（locator_basic.py）
  ├─ 采样（3×3 投票）
  ├─ 解码（repetition ECC）
  └─ 帧头解析
```

**问题**：
- 无法单独替换"布局"或"调制方式"
- 无法公平对比不同协议的收益
- 新协议必须重写整套 encoder/decoder

### 目标架构

```
协议层次分离：

┌─────────────────────────────────────────┐
│  Transmission Layer (不变)               │
│  - manifest.py                          │
│  - packing.py                           │
│  - assembler.py                         │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│  Protocol Interface (新增)               │
│  - ProtocolEncoder                      │
│  - ProtocolDecoder                      │
│  - LayoutInfo                           │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│  Protocol Implementations (并存)         │
│  - basic (稳定主线)                      │
│  - compact (实验 1: 压缩布局)            │
│  - gray4 (实验 2: 4-gray 调制)           │
│  - pilot (实验 3: 导频符号)              │
└─────────────────────────────────────────┘
```

### 接口定义

```python
# src/screen_airdrop/common/protocol_interface.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Tuple
import numpy as np

@dataclass
class LayoutInfo:
    """协议布局信息（sender/receiver 共享）"""
    frame_w: int          # 总宽度（modules）
    frame_h: int          # 总高度（modules）
    data_capacity: int    # 有效载荷容量（bits）
    protocol_name: str    # 协议名称
    protocol_version: int # 协议版本

class ProtocolEncoder(ABC):
    """协议编码器接口"""

    @abstractmethod
    def get_layout(self) -> LayoutInfo:
        """返回布局信息"""
        pass

    @abstractmethod
    def encode_frame(self, header: bytes, payload: bytes) -> np.ndarray:
        """编码单帧

        Args:
            header: 帧头（已序列化）
            payload: 载荷数据

        Returns:
            modules: (frame_h, frame_w) 二值或灰度数组
        """
        pass

class ProtocolDecoder(ABC):
    """协议解码器接口"""

    @abstractmethod
    def get_layout(self) -> LayoutInfo:
        """返回布局信息"""
        pass

    @abstractmethod
    def locate_frame(self, frame: np.ndarray, roi: Optional[Tuple[int,int,int,int]]) -> LocateResult:
        """定位帧"""
        pass

    @abstractmethod
    def decode_frame(self, modules: np.ndarray) -> Tuple[bytes, bytes]:
        """解码单帧

        Args:
            modules: (frame_h, frame_w) 采样后的模块数组

        Returns:
            (header, payload): 帧头和载荷数据
        """
        pass
```

---

## 实验协议设计

### 实验 1: Compact 协议（压缩布局）

**目标**: 减小 quiet zone / guard band，提升有效载荷比例

**改动**:
```
当前 basic:
- quiet: 4 modules
- finder: 9×9
- guard: 2 modules
- grid: 160×96
- 总尺寸: 190×126 = 23,940
- 有效载荷: 15,360 (64.2%)

实验 compact:
- quiet: 2 modules (-50%)
- finder: 7×7 (-44%)
- guard: 1 module (-50%)
- grid: 172×108 (+13%)
- 总尺寸: 190×126 = 23,940 (不变)
- 有效载荷: 18,576 (77.6%) (+21% 容量)
```

**实现**:
- 文件: `src/screen_airdrop/sender/encoder_compact.py`
- 文件: `src/screen_airdrop/receiver/decoder_compact.py`
- 复用: `locator_basic.py`（只改布局参数）

**风险**:
- Finder pattern 缩小可能降低检测成功率
- Quiet zone 缩小可能受窗口边框干扰

**验证**:
- 在 replay 模式下对比 `basic` vs `compact` 的解码成功率
- 如果成功率下降 <5%，则收益可接受

### 实验 2: Gray4 协议（4-gray 调制）

**目标**: 用 4 级灰度替代二值，容量翻倍

**改动**:
```
当前 basic:
- 调制: 二值 (0/1)
- 每 module: 1 bit
- 容量: 15,360 bits

实验 gray4:
- 调制: 4-gray (0/85/170/255)
- 每 module: 2 bits
- 容量: 30,720 bits (2× 容量)
```

**实现**:
- 文件: `src/screen_airdrop/sender/encoder_gray4.py`
- 文件: `src/screen_airdrop/receiver/decoder_gray4.py`
- 采样: 改用 k-means 聚类或最小距离判决

**风险**:
- RDP JPEG 压缩可能破坏灰度层次
- 需要更高的 SNR（信噪比）

**验证**:
- 先在 loopback 模式（无压缩）验证 4-gray 解码正确性
- 再在 RDP 模式验证误码率是否可接受
- 如果误码率 >10%，考虑降级到 3-gray 或自适应调制

### 实验 3: Header/Data 分层协议

**目标**: 把帧头和载荷分开编码，帧头用高 ECC，载荷用低 ECC

**改动**:
```
当前 basic:
- Header + payload 统一编码
- 统一 ECC level (L/M/Q/H)
- Header 错误 → 整帧丢弃

实验 layered:
- Header 区域: 固定位置，ECC=H (4× repetition)
- Payload 区域: 剩余空间，ECC=L (1× repetition)
- Header 错误 → 只丢 header，payload 可能部分恢复
```

**布局**:
```
┌─────────────────────────────────────┐
│ [Finder patterns]                   │
├─────────────────────────────────────┤
│ [Header zone: 固定 200 modules]      │  ← ECC=H
├─────────────────────────────────────┤
│                                     │
│   [Payload zone: 剩余空间]           │  ← ECC=L
│                                     │
└─────────────────────────────────────┘
```

**收益**:
- Header 鲁棒性提升（误码率 <0.1%）
- Payload 容量提升（ECC 开销从 4× 降到 1×）
- 总容量提升 ~30-40%

**实现**:
- 文件: `src/screen_airdrop/sender/encoder_layered.py`
- 文件: `src/screen_airdrop/receiver/decoder_layered.py`

---

## 实验 4: Pilot-Grid 协议（导频符号 + 跟踪）

**目标**: 用导频符号替代 timing patterns，支持帧间跟踪

**注意**: 这是**最后一个实验**，只在前三个实验验证后才考虑

**改动**:
```
基于 compact 协议，增加:
- 导频符号: 分散在 grid，密度 ~2-4%
- 帧间跟踪: 缓存透视矩阵，后续帧快速验证
- 自适应回退: 检测到窗口移动时重新定位
```

**收益**:
- 定位延迟: 首帧 30ms，后续帧 5-8ms（-75% 平均延迟）
- 相位校准: 用导频符号替代 timing patterns（-50% 开销）
- 信道估计: 实时评估 RDP 压缩质量，自适应调整 ECC

**实现**:
- 文件: `src/screen_airdrop/sender/encoder_pilot.py`
- 文件: `src/screen_airdrop/receiver/locator_pilot.py`
- 文件: `src/screen_airdrop/receiver/tracker.py`

**注意**: 这个实验**不应该现在就做**，原因：
1. 当前主瓶颈是屏幕捕获（50-70ms），不是定位（20-30ms）
2. 手动 ROI 模式下定位已经相对轻量
3. 帧间跟踪的收益需要在高帧率场景下才明显（>20 FPS）

**建议**: 等前三个实验验证后，如果帧率提升到 20+ FPS，再考虑这个优化

---

## 实现路线图

### Phase 0: 架构重构（1 周）

**目标**: 解耦协议实现，支持多协议并存

**任务**:

1. **定义协议接口**
   - 文件: `src/screen_airdrop/common/protocol_interface.py`
   - 内容: `ProtocolEncoder`, `ProtocolDecoder`, `LayoutInfo`

2. **重构 basic 协议**
   - 文件: `src/screen_airdrop/protocols/basic/encoder.py`
   - 文件: `src/screen_airdrop/protocols/basic/decoder.py`
   - 目标: 实现 `ProtocolEncoder` 和 `ProtocolDecoder` 接口
   - 保持: 功能完全不变，只是代码重组

3. **更新 controller 和 pipeline**
   - 修改: `src/screen_airdrop/sender/controller.py`
   - 修改: `src/screen_airdrop/receiver/pipeline.py`
   - 改动: 通过接口调用协议，而不是直接调用 `encoder_basic`

4. **回归测试**
   - 运行: `uv run pytest`
   - 验证: 所有测试通过，吞吐无变化

**验收标准**:
- [ ] 所有测试通过
- [ ] 可以通过配置切换协议（`--protocol basic`）
- [ ] 吞吐和延迟与重构前一致

---

### Phase 1: Compact 协议（1 周）

**目标**: 验证压缩布局的可行性（+21% 容量）

**任务**:

1. **实现 compact encoder**
   - 文件: `src/screen_airdrop/protocols/compact/encoder.py`
   - 改动: quiet=2, finder=7×7, guard=1, grid=172×108

2. **实现 compact decoder**
   - 文件: `src/screen_airdrop/protocols/compact/decoder.py`
   - 复用: `locator_basic.py`（只改布局参数）

3. **单元测试**
   - 文件: `tests/unit/test_protocol_compact.py`
   - 验证: 编码/解码正确性

4. **集成测试**
   - 运行: `pytest tests/integration/test_receiver_loopback.py --protocol compact`
   - 对比: `basic` vs `compact` 的解码成功率

**验收标准**:
- [ ] Loopback 模式解码成功率 >95%
- [ ] 容量提升 +21%
- [ ] 如果成功率 <95%，分析失败原因（finder 太小？quiet 太小？）

---

### Phase 2: Gray4 协议（2 周）

**目标**: 验证 4-gray 调制的可行性（2× 容量）

**任务**:

1. **实现 gray4 encoder**
   - 文件: `src/screen_airdrop/protocols/gray4/encoder.py`
   - 改动: 每 module 编码 2 bits，灰度值 [0, 85, 170, 255]

2. **实现 gray4 decoder**
   - 文件: `src/screen_airdrop/protocols/gray4/decoder.py`
   - 采样: 用最小距离判决或 k-means 聚类

3. **Loopback 测试**
   - 运行: `pytest tests/integration/test_receiver_loopback.py --protocol gray4`
   - 验证: 无压缩场景下解码正确性

4. **RDP 压缩测试**
   - 运行: 真实 RDP 传输测试
   - 测量: 误码率（BER）

**验收标准**:
- [ ] Loopback 模式解码成功率 >98%
- [ ] RDP 模式误码率 <10%
- [ ] 如果误码率 >10%，考虑降级到 3-gray 或自适应调制

---

### Phase 3: Layered 协议（1-2 周）

**目标**: 验证 header/data 分层的收益（+30-40% 容量）

**任务**:

1. **实现 layered encoder**
   - 文件: `src/screen_airdrop/protocols/layered/encoder.py`
   - 布局: Header zone (200 modules, ECC=H) + Payload zone (剩余, ECC=L)

2. **实现 layered decoder**
   - 文件: `src/screen_airdrop/protocols/layered/decoder.py`
   - 逻辑: 分别解码 header 和 payload

3. **集成测试**
   - 运行: `pytest tests/integration/test_receiver_lossy.py --protocol layered`
   - 对比: `basic` vs `layered` 在有损场景下的恢复率

**验收标准**:
- [ ] Header 解码成功率 >99.9%
- [ ] Payload 容量提升 +30-40%
- [ ] 有损场景下整体恢复率提升 >20%

---

### Phase 4: 性能对比和选型（1 周）

**目标**: 对比所有协议，选择最优方案

**任务**:

1. **Benchmark 对比**
   - 运行: `uv run python bench/run_benchmark.py --protocols basic,compact,gray4,layered`
   - 指标: 容量、吞吐、误码率、延迟

2. **生成对比报告**
   - 文件: `bench/results/protocol_comparison.md`
   - 内容: 表格 + 图表

3. **选型决策**
   - 如果 `compact` 成功率 >95% → 采用 `compact` 作为新默认协议
   - 如果 `gray4` 误码率 <5% → 考虑混合方案（header 用 binary，payload 用 gray4）
   - 如果 `layered` 恢复率提升 >20% → 采用分层设计

**验收标准**:
- [ ] 有完整的性能对比数据
- [ ] 有明确的选型建议
- [ ] 新协议吞吐提升 >1.5×

---

### Phase 5: Pilot-Grid 协议（可选，2-3 周）

**前置条件**: Phase 1-4 完成，且帧率已提升到 >20 FPS

**目标**: 验证帧间跟踪的收益（-75% 定位延迟）

**任务**:

1. **实现导频符号生成**
   - 文件: `src/screen_airdrop/protocols/pilot/encoder.py`
   - 逻辑: 在 grid 中嵌入伪随机序列

2. **实现导频符号检测**
   - 文件: `src/screen_airdrop/protocols/pilot/locator.py`
   - 逻辑: 相关性匹配 + 相位估计

3. **实现帧间跟踪**
   - 文件: `src/screen_airdrop/receiver/tracker.py`
   - 状态机: COLD_START → TRACKING → LOST

4. **集成测试**
   - 运行: `pytest tests/integration/test_receiver_loopback.py --protocol pilot`
   - 测量: 首帧延迟 vs 后续帧延迟

**验收标准**:
- [ ] 首帧定位延迟 ~30ms
- [ ] 后续帧定位延迟 <10ms
- [ ] 跟踪成功率 >90%（窗口静止场景）

**注意**: 这个 phase 只在前面的优化已经把帧率提升到 >20 FPS 后才有意义

---

## 风险评估和缓解

### 1. Compact 协议风险

**风险**: Finder pattern 缩小可能降低检测成功率

**缓解**:
- 先在 loopback 模式验证
- 如果失败率 >5%，考虑只缩小 quiet zone，保持 finder=9×9
- 或者用混合方案：首帧用 9×9，后续帧用 7×7

### 2. Gray4 协议风险

**风险**: RDP JPEG 压缩可能破坏灰度层次

**缓解**:
- 先在无压缩场景验证
- 测量不同 RDP 质量设置下的误码率
- 如果误码率 >10%，考虑：
  - 降级到 3-gray（1.5× 容量）
  - 自适应调制（根据信道质量动态切换 binary/gray4）
  - 只在 header 用 binary，payload 用 gray4

### 3. 兼容性风险

**风险**: 新协议与旧版本不兼容

**缓解**:
- 保留 `basic` 协议作为默认
- 在 sync frame 中嵌入协议版本号
- Receiver 自动检测协议类型
- 提供 `--protocol` 参数手动指定

### 4. 性能回退风险

**风险**: 新协议可能在某些场景下性能更差

**缓解**:
- 每个 phase 都有明确的验收标准
- 如果验收失败，不合并到主线
- 保持 `basic` 协议作为 fallback
- 提供协议切换机制

---

## 预期收益

### 保守估计（只做 Phase 1-3）

| 指标 | 当前 (basic) | 优化后 | 提升 |
|------|-------------|--------|------|
| **有效载荷比例** | 64.2% | 80-85% | +25-33% |
| **单帧容量** | 15,360 bits | 19,000-20,000 bits | +24-30% |
| **实际吞吐** | 8-10 KB/s | 12-16 KB/s | **1.5-2×** |

### 激进估计（做 Phase 1-5）

| 指标 | 当前 (basic) | 优化后 | 提升 |
|------|-------------|--------|------|
| **有效载荷比例** | 64.2% | 85-90% | +33-40% |
| **定位延迟（平均）** | 25ms | 10ms | -60% |
| **理论帧率** | 15 FPS | 30 FPS | +100% |
| **实际吞吐** | 8-10 KB/s | 20-30 KB/s | **2.5-3×** |

---

## 总结

### 核心策略

1. **不破坏 basic 主线**：通过架构重构支持多协议并存
2. **先优化单帧容量**：Phase 1-3 聚焦在布局和调制优化
3. **后优化定位跟踪**：Phase 5 只在帧率提升后才考虑
4. **每步都验证收益**：每个 phase 都有明确的验收标准

### 关键里程碑

- **Week 1**: 架构重构完成，支持多协议
- **Week 2**: Compact 协议验证，容量 +21%
- **Week 4**: Gray4 协议验证，容量 2×（如果 RDP 支持）
- **Week 6**: Layered 协议验证，容量 +30-40%
- **Week 7**: 性能对比，选择最优方案
- **Week 10** (可选): Pilot-Grid 协议，定位延迟 -75%

### 预期最终收益

- **保守**: 1.5-2× 吞吐提升（只做 Phase 1-3）
- **激进**: 2.5-3× 吞吐提升（做 Phase 1-5）

---

**文档版本**: v2.0（基于 codex 分析重写）
**作者**: Claude Opus 4.6
**日期**: 2026-03-07
