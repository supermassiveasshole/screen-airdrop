# screen-airdrop 需求规格说明书（仅屏幕调制传输）

## Implementation Status (2026-03-04)

Current repository now includes:

* Dual sender entrypoints:
  * `screen-airdrop-sender-legacy` (Python 3.7.6 compatible)
  * `screen-airdrop-sender` (modern Python)
* Realtime sender pipeline: package/compress/chunk -> frame encode -> OpenCV autoplay loop.
* Realtime receiver pipeline: MSS capture -> frame decode -> chunk assemble -> restore + SHA-256 verification.
* Shared protocol/manifest/packing modules under `src/screen_airdrop/common`.
* Packaging and delivery scripts:
  * offline wheelhouse install helper
  * CentOS 7 onefile sender build Dockerfile/script

Quickstart (local modern environment):

```bash
uv sync --group dev
uv run screen-airdrop-sender ./path/to/input --window-name "screen-airdrop"
uv run screen-airdrop-receiver --source screen --window-title "Remote Desktop" --output-dir ./recovered
```

V3.1 four-corner fixed-grid protocol (default):

```bash
uv run screen-airdrop-sender ./path/to/input \
  --protocol v3_1 \
  --ecc-level Q \
  --module-grid 160x96 \
  --guard-band-modules 2 \
  --corner-size-modules 9

uv run screen-airdrop-receiver \
  --source screen \
  --protocol v3_1 \
  --detect-mode track \
  --locator-engine auto \
  --locator-confidence-threshold 0.55 \
  --track-margin-px 96 \
  --output-dir ./recovered \
  --report-json ./recovered/receiver_report.json
```

关键说明：

* `v3_1` 主链使用“四角定位 + 固定网格切分 + 模块中心采样”。
* `--locator-engine` 支持 `new|legacy|auto`，默认 `auto`，行为是先 `new`，失败或置信度不足再回退 `legacy`。
* 接收端默认 `track`：首帧全局定位，成功后局部跟踪，连续失败自动回全局。
* `v3_1` 路径不再回退到旧 `v3` 协议解码。

V2 auto locator + manual ROI fallback (recommended):

```bash
uv run screen-airdrop-sender ./path/to/input --protocol v2 --quiet-zone-px 48
uv run screen-airdrop-receiver \
  --source screen \
  --protocol v2 \
  --roi-mode auto_then_manual \
  --select-region \
  --roi-profile ~/.screen-airdrop-roi.json \
  --output-dir ./recovered \
  --report-json ./recovered/receiver_report.json
```

Manual-only ROI mode:

```bash
uv run screen-airdrop-receiver \
  --source screen \
  --protocol v2 \
  --roi-mode manual \
  --select-region

# Manual ROI tips:
# 1) You can select either the full white locator frame OR payload area only.
# 2) Enter confirm / R reselect / Esc cancel.
```

Legacy sender (Python 3.7.6 server):

```bash
screen-airdrop-sender-legacy /path/to/input --window-name "screen-airdrop"
```

Packaging:

```bash
./scripts/build_wheelhouse.sh
./scripts/build_centos7_sender.sh
```

## 速率测试

运行快速 replay 基准：

```bash
uv run python bench/run_benchmark.py --mode replay --quick
uv run python bench/summarize.py
```

完整 replay 基准（3 次重复 + 参数矩阵）：

```bash
uv run python bench/run_benchmark.py --mode replay --repeats 3

# 指定协议做对比
uv run python bench/run_benchmark.py --mode replay --protocol v3_1 --repeats 3
uv run python bench/run_benchmark.py --mode replay --protocol v3 --repeats 3
```

输出文件：

* `bench/results/benchmark_*.json`
* `bench/results/summary_*.json`
* `bench/results/summary.md`

## 指标解释

* `raw_frame_rate_fps`: 接收端处理的总帧率（含坏帧）
* `valid_frame_rate_fps`: CRC/解码通过的有效帧率
* `goodput_kibps`: 有效 payload 吞吐（单位 KiB/s，核心速率指标）
* `end_to_end_kibps`: 从开始到恢复完成的端到端吞吐（单位 KiB/s）
* `bad_frame_rate`: 坏帧占比
* `recovery_latency_s`: 从接收到首个数据帧到恢复完成耗时
* `protocol_path_used`: 本次主用解码路径（`v3_1` 或 `v3`）
* `decode_attempts_per_frame`: 平均每帧解码尝试次数（越低越快）
* `fallback_ratio`: 回退到旧 `v3` 的比例
* `homography_stability`: 连续帧检测框抖动均值（越低越稳）

为什么优先看 `goodput_kibps`：

* `raw fps` 无法反映有效负载，可能“帧率高但有效数据少”
* `goodput` 更接近真实传输效率

常见瓶颈排查：

1. `bad_frame_rate` 高：优先调大 `block-size`（如 8）与阈值策略。
2. `valid_frame_rate_fps` 低：检查截屏区域/窗口定位是否稳定。
3. `end_to_end_kibps` 低：检查 `chunk-size` 与 `fps` 是否匹配当前分辨率容量。

## 0. 摘要

screen-airdrop 是一个在受限环境（离线/隔离/无网络文件通道）下，通过远程桌面可见屏幕将服务器文件导出到本机的工具。

本项目只实现一种传输方式：

* 发送端将文件编码为可视帧并在远程桌面持续播放。
* 接收端在本机窗口截屏、解码、重组并恢复文件。

不依赖共享目录、驱动器映射、剪贴板文件传输等回传通道。

---

## 1. 目标与非目标

### 1.1 目标

* 从服务器导出文件或目录到本机。
* 发送端尽量仅依赖 Python 标准库（Python 3.7.6）。
* 在远程桌面画面压缩、卡顿、重复帧下仍可最终收齐文件。
* 提供可观测的实时指标：吞吐、帧成功率、CRC 失败率、预计剩余时间。
* 在 1080p 典型环境下基线吞吐达到 **>=200 KB/s**，条件良好目标 **>=1 MB/s**。

### 1.2 非目标

* 不提供端到端加密、身份认证、权限系统。
* 不对抗恶意篡改（仅做误码检测与恢复）。
* 不支持“无图形输出/无远程桌面显示”的服务器。
* 不保证在任意分辨率和任意刷新率下都达到目标吞吐。

---

## 2. 术语与约定

* Session：一次文件传输任务的唯一会话。
* Frame：屏幕播放的一帧编码画面。
* Chunk：payload 切片后的最小数据单元。
* Epoch：发送端循环播放全量 Frame 的轮次。
* Manifest：会话元信息（文件结构、哈希、参数）。
* ROI（Region of Interest）：接收端截屏并解码的窗口区域。

单位与编码：

* 默认字节序：little-endian。
* 字符串编码：UTF-8。
* 哈希算法：SHA-256。
* 帧内校验：CRC32。

---

## 3. 系统架构

screen-airdrop = **Sender + Receiver + Protocol**

* Sender（服务器）：打包、压缩、分片、帧编码、循环播放。
* Receiver（本机）：窗口定位、截屏采样、帧解码、去重补齐、重组校验。
* Protocol（共享逻辑）：帧头格式、manifest 格式、校验规则、状态码。

数据流：

1. Sender 将输入目录打包并压缩为 payload。
2. payload 切片为 chunk，映射为 Frame 序列。
3. Frame 序列循环播放到远程桌面窗口。
4. Receiver 持续截屏并解码 Frame。
5. 收齐全部 chunk 后重组、解压、恢复目录并做最终 SHA-256 校验。

---

## 4. 端到端流程

### 4.1 发送流程

1. 解析输入路径（文件或目录）。
2. 生成 tar（保留层级与权限元数据）。
3. 压缩（默认 gzip，可选 none）。
4. 生成 manifest。
5. 按 `chunk_size` 切片并构造 Frame。
6. 先播放同步帧（Sync），再循环播放数据帧（Data）。

### 4.2 接收流程

1. 选择目标窗口并锁定 ROI。
2. 读取 Sync 帧，完成网格定位与阈值校准。
3. 进入 Data 捕获循环，按 `session_id + frame_id` 去重。
4. CRC32 验证通过则写入 chunk 缓存。
5. 检测缺失 chunk，等待后续 Epoch 自动补齐。
6. 全量收齐后重组 payload 并解压恢复。
7. 对照 manifest 执行 SHA-256 终验。

---

## 5. Sender 规格（服务器）

### 5.1 环境与依赖

* Python 3.7.6。
* 标准库必备：`os` `tarfile` `zlib` `hashlib` `struct` `json` `time`。
* 不要求 OpenCV、NumPy、GPU、系统级 GUI 库。

### 5.2 打包与压缩

* 输入支持单文件和目录。
* 打包格式固定：`tar`。
* 压缩算法：`gzip`（默认）或 `none`。
* 输出逻辑对象：
  * `payload.bin`（内存流或临时文件）
  * `manifest.json`

### 5.3 分片

* 默认 `chunk_size = 16384`（16 KB），允许 8 KB~64 KB。
* `total_chunks = ceil(payload_size / chunk_size)`。
* 末尾 chunk 允许不足 `chunk_size`。

### 5.4 播放要求

* 播放模式：窗口内全屏绘制（边框可留安全区）。
* 目标帧率：8~20 FPS，可配置。
* 必须循环播放，直到用户手动结束或达到 `max_epochs`。

---

## 6. Receiver 规格（本机）

### 6.1 环境与依赖

* Python 3.10+。
* 推荐依赖：`mss` `numpy` `opencv-python`（可替换）。
* 可选硬件加速：GPU（非必需）。

### 6.2 功能责任

* ROI 选取与透视/缩放修正。
* 二值化与网格采样。
* 帧头解析、payload 还原、CRC32 校验。
* chunk 去重与缺块追踪。
* 收齐后重组、解压与落盘。
* 输出统计：FPS、解码成功率、当前吞吐。

### 6.3 容错要求

* 对重复帧必须幂等处理。
* 对坏帧（CRC 失败）必须丢弃并计数。
* 对短时卡顿必须自动恢复，不中断会话。

---

## 7. 屏幕协议规格（核心）

### 7.1 画面布局

每帧由三部分组成：

1. 定位区（四角定位标记 + 边缘参考条）
2. Header 区（高鲁棒编码，低密度）
3. Payload 区（高密度网格编码）

### 7.2 Header 字段（必须）

固定长度二进制结构（建议 48 字节）：

* `magic` `uint32`：固定值 `0x53415244`（"SARD"）
* `version` `uint8`：协议版本，当前 `1`
* `frame_type` `uint8`：`0=sync` `1=data` `2=end`
* `flags` `uint16`：保留位
* `session_id` `uint64`
* `epoch_id` `uint32`
* `frame_id` `uint32`
* `total_frames` `uint32`
* `chunk_id` `uint32`（仅 data 帧有效）
* `payload_len` `uint16`
* `header_crc32` `uint32`
* `payload_crc32` `uint32`

### 7.3 Payload 编码

* 默认模式：1 bit/block（二值黑白）。
* `block_size` 可配置：`4|6|8`（像素）。
* 采样规则：取每个 block 中心 `3x3` 子区域均值判定。
* 比特序：行优先（row-major）。

### 7.4 Sync 帧

* 每个 Session 启动时连续发送 `sync_frames >= 30`。
* 包含棋盘格、灰阶条、角标 ID。
* Receiver 用于：
  * ROI 锁定
  * 亮度阈值校准
  * 缩放与轻微透视矫正

### 7.5 End 帧

* 全量 Data 至少完成 1 个 Epoch 后发送 End 帧。
* End 帧仅作为“发送完成提示”，不代表接收已收齐。

---

## 8. Manifest 规格

### 8.1 顶层字段

* `protocol_version`
* `session_id`
* `created_at`
* `input_root_name`
* `pack`（`tar`）
* `compress`（`gzip|none`）
* `chunk_size`
* `total_chunks`
* `payload_size`
* `payload_sha256`
* `entries`（文件条目列表）

### 8.2 entries 字段

每项包含：

* `path`
* `type`（`file|dir|symlink`）
* `size`
* `mode`
* `mtime`
* `sha256`（文件类型可选，建议启用）

---

## 9. 状态机与重传策略

### 9.1 Sender 状态机

`INIT -> PACK -> ENCODE -> SYNC -> DATA_LOOP -> END_LOOP -> DONE`

* `DATA_LOOP`：按 `frame_id=0..N-1` 连续输出。
* 一个 Epoch 完成后 `epoch_id += 1` 并重头播放。

### 9.2 Receiver 状态机

`INIT -> CALIBRATE -> CAPTURE -> ASSEMBLE -> VERIFY -> RESTORE -> DONE`

* `CAPTURE` 阶段维护 `missing_chunks` 集合。
* 当 `missing_chunks` 为空时进入 `ASSEMBLE`。

### 9.3 重传机制

* 无反向 ACK 通道。
* 通过 Epoch 广播式自然重传。
* 高丢帧场景通过更大 block size 降低误码率。

---

## 10. 参数与默认值

### 10.1 发送端

* `--chunk-size` 默认 `16384`
* `--block-size` 默认 `6`
* `--fps` 默认 `12`
* `--compress` 默认 `gzip`
* `--sync-frames` 默认 `30`
* `--max-epochs` 默认 `0`（0 表示无限循环）

### 10.2 接收端

* `--window-title` 必填（或 `--roi`）
* `--block-size` 默认 `auto`
* `--threshold` 默认 `auto`
* `--max-idle-seconds` 默认 `30`
* `--output-dir` 默认当前目录

---

## 11. CLI 规格

### 11.1 sender

```bash
screen-airdrop sender /path/to/input \
  --compress gzip \
  --chunk-size 16384 \
  --block-size 6 \
  --fps 12
```

### 11.2 receiver

```bash
screen-airdrop receiver \
  --window-title "Remote Desktop" \
  --output-dir ./recovered \
  --block-size auto
```

### 11.3 运行输出（必须）

* `session_id`
* `epoch/frame`
* `decoded_chunks/total_chunks`
* `fps`
* `throughput_kibps`
* `crc_fail_rate`
* `eta`

---

## 12. 错误码与失败语义

* `E1001`：输入路径不存在
* `E1002`：打包失败
* `E1003`：压缩失败
* `E2001`：无法定位 ROI
* `E2002`：同步校准失败
* `E2003`：帧头 CRC 错误
* `E2004`：payload CRC 错误
* `E3001`：重组后 SHA-256 不一致
* `E3002`：解压/恢复失败

失败要求：

* 输出错误码与简明原因。
* 保留中间产物（可配置清理）。
* 支持同一 `session_id` 继续捕获补齐。

---

## 13. 性能指标与基准

### 13.1 验收性能

* 1080p，`block=8`：>=200 KB/s。
* 1080p，`block=4~6`，网络稳定：目标 >=1 MB/s。
* 1 GB 文件传输最终 SHA-256 一致。

### 13.2 基准输出

`bench/` 需产出：

* 不同 block size 的吞吐曲线。
* 不同 FPS 的 CRC 失败率。
* 总用时、有效负载比（payload/frame_bits）。

---

## 14. 交付物

必须交付：

* `sender.py`：打包、压缩、分片、帧编码、播放。
* `receiver.py`：截屏、解码、去重、重组、恢复。
* `protocol.py`：Header/Manifest/CRC/状态码。
* `README.md`：本规格与操作步骤。
* `bench/`：基准脚本与结果样例。

---

## 15. 验收标准

1. 功能正确性：
* 文件与目录均可传输并恢复。
* 恢复结果与源数据 SHA-256 一致。

2. 鲁棒性：
* 出现重复帧、间歇卡顿时仍可最终收齐。
* CRC 错误帧不会污染最终结果。

3. 性能：
* 在 1080p 条件下达到基线吞吐（>=200 KB/s）。

4. 可运维性：
* 日志可定位失败阶段与错误码。
* 参数可调，默认值可直接完成常规传输。

---

## 16. 后续可选增强（不影响本期验收）

* 灰度 2-bit 编码（4 灰度）提升单位帧吞吐。
* FEC（Reed-Solomon）减少高误码场景等待时间。
* 多窗口/多显示器自动识别。
* SIMD/GPU 解码加速。
