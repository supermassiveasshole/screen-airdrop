⸻

Screen-Airdrop

Screen-Only Data Transfer Protocol

Software Requirements Specification (SRS)

Version: 1.0

⸻

1. System Overview

screen-airdrop 是一种 基于屏幕输出的单向数据传输系统。

数据通过以下路径传输：

Remote Server
   │
   │ render encoded frames
   ▼
Remote Desktop Stream
   │
   │ screen capture
   ▼
Local Receiver
   │
   │ decode frames
   ▼
Recovered Files

特点：
	•	不依赖网络文件传输
	•	不依赖 USB
	•	不依赖共享目录
	•	仅依赖 屏幕显示

⸻

2. Design Goals

系统必须满足：

2.1 Robust Position Detection

Receiver 不依赖：
	•	窗口位置
	•	窗口大小
	•	DPI
	•	分辨率

必须通过 Sync Layer 自动定位数据区域。

⸻

2.2 Automatic Grid Lock

Receiver 必须自动估计：

block_size
grid_origin
threshold


⸻

2.3 High Throughput

目标：

≥ 1 MB/s

理想：

5 MB/s


⸻

2.4 Sender Simplicity

Sender 必须：
	•	依赖最少
	•	可仅使用 Python 标准库

Receiver 可以使用：
	•	OpenCV
	•	NumPy
	•	GPU

⸻

3. Frame Structure

每帧由三部分组成：

+---------------------------+
| Sync Layer                |
+---------------------------+
| Header                    |
+---------------------------+
| Payload Matrix            |
+---------------------------+


⸻

4. Sync Layer

Sync Layer 用于：

position detection
scale estimation
grid alignment
threshold calibration

Sync Layer 包含三种结构：

PN stripes
Checkerboard
Hadamard pattern


⸻

5. PN Stripe

用于粗定位。

Horizontal PN stripe

█░█░░█░█░█░░░█░░█░█░█░░█

长度：

≥127 bits

高度：

≥4 payload blocks


⸻

Vertical PN stripe

同样结构：

█░█░░█░█░█░░░█░░█░█░█░░█

用于：

X axis detection
Y axis detection


⸻

6. Checkerboard Pattern

大规模棋盘格：

█░█░█░█░
░█░█░█░█
█░█░█░█░
░█░█░█░█

尺寸：

≥40×40 blocks

用途：

estimate block size
estimate threshold


⸻

7. Hadamard Sync Frame

session 开始时播放：

5–10 frames

内容：

Hadamard matrix pattern

推荐：

32×32 blocks

优点：

orthogonal pattern
robust detection

Receiver 通过 correlation 检测。

⸻

8. Header Structure

Header 编码使用更大 block：

block_size × 2

结构：

magic (2 bytes)
version (1 byte)
frame_id (4 bytes)
total_frames (4 bytes)
payload_length (2 bytes)
payload_crc32 (4 bytes)


⸻

9. Payload Matrix

Payload 为 block grid。

block 颜色：

white = 0
black = 1

推荐 block 尺寸：

6×6 pixels

可选：

4×4 high throughput
8×8 high robustness


⸻

10. Self-Clocking Encoding

Payload 必须使用：

Manchester encoding

规则：

0 → 01
1 → 10

目的：

avoid long constant sequences
enable phase correction


⸻

11. Receiver Pipeline

Receiver 每帧执行：

screen capture
↓
PN stripe detection
↓
ROI estimation
↓
block size estimation
↓
grid phase estimation
↓
threshold estimation
↓
header decode
↓
payload decode
↓
Manchester decode
↓
CRC verification


⸻

12. Block Size Estimation

Receiver 使用：

FFT
or
autocorrelation

检测棋盘格周期。

输出：

block_size_px


⸻

13. Grid Phase Estimation

Receiver 搜索：

dx ∈ [0, block_size)
dy ∈ [0, block_size)

最大 correlation 对应：

grid_origin


⸻

14. Threshold Estimation

在棋盘格区域采样：

μ_black
μ_white

阈值：

T = (μ_black + μ_white)/2


⸻

15. Sampling Method

每个 block 采样：

center window

大小：

0.3 × block_size

避免：

edge blur
antialiasing


⸻

16. Frame Transmission

Sender 使用：

cyclic broadcast

发送顺序：

frame1
frame2
...
frameN
repeat

Receiver：

store unseen frames
ignore duplicates


⸻

17. Error Detection

每帧使用：

CRC32

Receiver 行为：

CRC fail → discard frame

最终文件使用：

SHA256

验证完整性。

⸻

18. Receiver State Machine

SEARCH
   │
   ▼
SYNC DETECTION
   │
   ▼
GRID LOCK
   │
   ▼
HEADER DECODE
   │
   ▼
PAYLOAD DECODE
   │
   ▼
CRC VERIFY
   │
   ├─ success → STORE
   │
   └─ fail → RELock


⸻

19. Performance Targets

1080p：

block	throughput
8×8	~250 KB/s
6×6	~500 KB/s
4×4	~1 MB/s

更高分辨率：

4K ≈ 4 MB/s


⸻

20. Implementation Requirements

Sender：

Python 3.7
standard library only

Receiver：

Python 3.10+
OpenCV
NumPy

推荐函数：

cv2.matchTemplate
cv2.dft
cv2.warpPerspective


⸻

21. File Packaging

Sender：

file
↓
tar
↓
zstd compression
↓
chunking
↓
Manchester encoding
↓
frame generation

Receiver：

frames
↓
reassembly
↓
decompression


⸻

22. Default Parameters

block_size = 6 px
hadamard_sync = 32×32
pn_length = 127
sync_frames = 8
sampling_window = 0.4 block


⸻

23. Testing Requirements

必须测试：

different DPI
window resize
frame drop
frame repeat
remote desktop compression


⸻

24. Key Design Principle

Receiver 不得假设任何固定像素坐标。

所有参数必须从 Sync Layer 推导：

position
scale
phase
threshold


⸻

25. Expected Result

系统在以下条件下稳定：

window moved
window resized
DPI scaling
remote desktop compression
frame drop


⸻
