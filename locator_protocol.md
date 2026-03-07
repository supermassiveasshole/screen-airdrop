下面是一份 **完整、可直接交付给实现者（或 Codex）的 V3.1 定位系统方案文档**。
它已经整合了我们之前所有讨论：**定位架构、合同规则、sender 布局、timing、ROI、quality、fallback、debug、性能预算**。

设计目标只有一个：

**多实现者并行开发也不会产生分叉。**

---

# Screen-Airdrop

# V3.1 定位系统实施规范（完整封版）

---

# 1. Summary

V3.1 将定位系统重构为 **独立视觉定位子系统**，与 payload 解码完全解耦。

核心目标：

1. **单帧稳定定位**
2. **支持手动 ROI 粗框**
3. **远程桌面环境可诊断**
4. **支持灰度上线与回滚**
5. **多实现者不产生行为分叉**

系统策略：

```
sender + receiver 同步改协议
locator-engine = auto(new → legacy)
```

ROI 语义：

```
ROI = 搜索限域
不是最终解码框
```

---

# 2. Architecture

系统分为两层：

```
Frame
│
├─ Geometry Layer
│   ├ finder detection
│   ├ quad estimation
│   ├ homography
│   ├ warp
│   ├ timing recovery
│   └ grid sampling
│
└─ Payload Layer
    ├ header decode
    ├ payload bits
    └ error correction
```

重要规则：

```
locator_v31 完全 payload-agnostic
```

locator 不允许依赖：

* header结构
* payload编码
* ECC
* frame sequencing

locator 唯一输出：

```
modules matrix
```

---

# 3. Global Contract Rules（铁律）

1️⃣ quad 顺序固定

```
quad_src = (tl, tr, br, bl)
```

索引固定：

```
[0] tl
[1] tr
[2] br
[3] bl
```

禁止使用任何其他顺序。

---

2️⃣ quad 坐标系

```
quad_src 坐标系 = 原始 frame 像素坐标
```

---

3️⃣ homography 方向

定义：

```
p_src = (x, y, 1)^T

p_std = H * p_src
```

结果：

```
(x_std, y_std) = (x'/w', y'/w')
```

矩阵：

```
H ∈ R^(3×3)
```

方向：

```
frame → warped
```

并定义：

```
homography_inv = H^-1
```

---

4️⃣ ROI 语义

ROI 仅用于：

```
搜索限域
```

禁止：

```
ROI = decode box
```

---

5️⃣ modules 来源

```
modules 必须来自

warped + grid_bbox_std
```

禁止：

```
在 warped 中重新检测 grid
```

---

6️⃣ fallback 条件

固定：

```
fail_reason != None
OR
confidence < threshold
```

---

# 4. Public API

新文件：

```
src/screen_airdrop/receiver/locator_v31.py
```

接口：

```
locate_frame(frame, search_roi=None, config=LocatorConfig)
    -> LocateResult | LocateError
```

---

## LocateResult

包含：

```
quad_src
homography
homography_inv
warped
grid_bbox_std
modules
quality
debug_artifacts
```

---

## LocateQuality

```
finder_score
geom_score
warp_rmse
timing_score
sampling_contrast
confidence
```

---

## LocateFailReason

```
NO_FINDER
BAD_FINDER_PATTERN
BAD_GEOMETRY
WARP_FAIL
TIMING_FAIL
LOW_CONTRAST
```

---

## modules 索引合同

```
modules[j][i] == grid(i,j)

i ∈ [0 .. Gx-1]
j ∈ [0 .. Gy-1]
```

shape：

```
(Gy, Gx)
```

---

## elapsed_ms 定义

```
elapsed_ms = locator_v31 总耗时
```

包含：

```
preprocess
finder
quad combination
warp
timing
sampling
```

不包含：

```
decoder
```

---

# 5. ROI Contract

允许：

```
ROI 子图检测
```

偏移定义：

```
roi_offset = (roi.x, roi.y)
```

回写规则：

```
quad_src = quad_src_local + roi_offset
```

逐点相加。

---

Debug 图规则：

```
quad_selected.png
必须绘制在 frame_raw 坐标系
```

---

# 6. Sender Absolute Layout

模块布局完全固定。

参数：

```
q       quiet zone modules
F       finder size modules
guard   guard band modules
Gx      grid width modules
Gy      grid height modules
timing_mode = rowcol
```

---

## Frame Size

```
frame_w = 2*q + 2*F + 2*guard + Gx
frame_h = 2*q + 2*F + 2*guard + Gy
```

---

## Finder 位置

```
A = (q, q)

B = (frame_w - q - F, q)

C = (q, frame_h - q - F)

D = (frame_w - q - F, frame_h - q - F)
```

---

## Data Grid 起点

```
grid_x0 = q + F + guard
grid_y0 = q + F + guard
```

---

## Data Grid 区域

```
x ∈ [grid_x0, grid_x0 + Gx)
y ∈ [grid_y0, grid_y0 + Gy)
```

---

# 7. Finder Pattern

Finder 结构固定：

```
黑外环 thickness = 1
白环 thickness = 1
黑中心核
```

必须：

```
硬边界
```

禁止：

```
灰阶过渡
```

---

# 8. Warp

标准图尺寸：

```
warp_std_w = warp_size
warp_std_h = round(warp_size * frame_h / frame_w)
```

保持纵横比。

---

warp 插值固定：

```
bilinear
```

---

# 9. Grid Bounding Box

grid_bbox_std 计算：

```
由 LayoutInfoV31 + warp 尺寸推导
```

禁止：

```
在 warped 中再次检测 grid
```

---

# 10. Timing Detection

Timing 分轴输出：

```
row → (T_x, phi_x, score_row)
col → (T_y, phi_y, score_col)
```

定义：

```
timing_score = min(score_row, score_col)
```

---

Timing 规则：

```
只能修正相位 (phi_x, phi_y)
```

禁止：

```
修改 cell spacing
```

---

cell spacing 来源：

```
LayoutInfoV31
+
warp 尺寸
```

---

# 11. Sampling

V3.1 MVP：

```
3×3 px 投票
```

在 warped 上采样。

---

# 12. Finder Candidate Filtering

定义：

```
expected_finder_px = warp_std_w * F / frame_w
```

候选 bbox 必须满足：

```
min_side >= 0.5 * expected_finder_px
max_side <= 2.0 * expected_finder_px
```

---

# 13. Quality Metrics

warp_rmse 定义：

```
quad_src 经 H
→ warp 四角

(0,0)
(W,0)
(W,H)
(0,H)
```

计算 4 点 RMSE。

单位：

```
warped 像素
```

---

归一化：

```
warp_rmse_norm =
min(1.0, warp_rmse / warp_rmse_threshold)
```

---

confidence 公式（固定）

```
confidence =
0.30 * finder_score +
0.25 * geom_score +
0.20 * (1 - warp_rmse_norm) +
0.15 * timing_score +
0.10 * sampling_contrast
```

---

timing 失败处理：

```
timing_used = false
fail_reason = TIMING_FAIL
confidence 降权
```

---

# 14. LayoutInfoV31

二进制结构：

```
layout_ver
q
F
guard
Gx
Gy
timing_mode
flags
crc16
```

字节序：

```
Little Endian
```

---

CRC：

```
CRC-16 / CCITT-FALSE
```

覆盖：

```
crc16 之前所有字节
```

---

flags 定义：

```
bit0  timing_enabled
bit1  reserved_alignment_pattern
bit2..7  must be zero
```

---

兼容规则：

```
无扩展区 → legacy 默认

有扩展区 + CRC OK → 使用扩展参数
```

---

# 15. Debug Artifact Standard

每帧 JSON：

```
locator_engine
roi_offset
finder_candidates
quad_src
warp_rmse
timing_score
confidence
fail_reason
elapsed_ms
legacy_used
legacy_elapsed_ms
new_fail_reason
new_elapsed_ms
```

---

Debug 图：

```
frame_raw.png
finder_candidates.png
quad_selected.png
warp.png
grid_overlay.png
sample_points.png
```

颜色规范：

```
finder      red
quad        green
grid        blue
samples     yellow
```

---

# 16. Performance Budget

总预算：

```
< 40 ms / frame
```

目标：

```
25 FPS
```

---

阶段预算：

```
preprocess      <5 ms
finder          <15 ms
quad select     <5 ms
warp            <5 ms
timing          <5 ms
sampling        <5 ms
```

---

组合复杂度限制：

```
topK ≤ 12

C(12,4) = 495
```

---

warp 尺寸：

```
默认 800 级
```

禁止：

```
4K 直接 warp
```

---

# 17. Rollout Strategy

CLI：

```
--locator-engine new
--locator-engine legacy
--locator-engine auto
```

默认：

```
auto
```

行为：

```
1 run new
2 if fail → fallback legacy
```

---

fallback 规则：

```
modules = legacy output
```

---

统计必须记录：

```
new_fail_reason
new_elapsed_ms
legacy_used
legacy_elapsed_ms
```

---

# 18. Implementation Order

1️⃣ 定义类型与合同常量
2️⃣ 实现 locator pipeline
3️⃣ 修改 decoder_v31 调用 locator
4️⃣ 修改 encoder_v31 绝对布局
5️⃣ 实现 LayoutInfoV31
6️⃣ 接入 CLI
7️⃣ 接入 debug artifacts
8️⃣ 接入 fallback 统计
9️⃣ 跑测试矩阵

---

# 19. Test Matrix

单测：

```
quad 顺序
ROI 偏移
warp aspect ratio
timing 分轴
warp_rmse
modules shape
```

---

集成：

```
1080p
1440p
4K
远程桌面
replay 样本
```

---

ROI 专项：

```
完整覆盖 → success
缺角 → fail + fail_reason
```

---

# 20. Assumptions

sender 保证：

```
四个 finder 可见
无遮挡
未裁切
```

用户 ROI：

```
粗略覆盖整个符号
```

---

默认：

```
sampling = 3×3
timing enabled
legacy 保留
```

---
