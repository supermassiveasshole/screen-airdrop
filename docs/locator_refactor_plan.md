# Locator重构计划

## 目标

将locator逻辑从decoder中完全分离，实现清晰的职责划分：
- **Locator**: 纯粹的几何定位（无状态函数）
- **FrameLocator**: ROI跟踪和engine选择（有状态）
- **GeometryTracker**: 状态机管理（lock/reacquire）
- **Decoder**: 纯粹的解码逻辑（不管理ROI/geometry状态）

## 当前问题

### 1. 状态管理混乱
- 旧pipeline: 状态在DecodeWorker线程中（`_track_roi`, `_locked_geometry`, `_lock_state`）
- 新runtime: GeometryTracker已经存在，但decoder仍然参与状态决策

### 2. Decoder职责过重
- Decoder需要知道`locator_engine`参数
- Decoder内部有`_run_locator()`函数，包含new/legacy/auto逻辑
- Decoder需要从meta提取geometry信息

### 3. ROI跟踪逻辑分散
- 成功后更新ROI的逻辑在pipeline/runtime中
- 失败后fallback逻辑在decoder中
- 没有统一的ROI管理器

### 4. CLI参数臃肿
- 9个locator相关参数，但用户只需要2个
- 内部参数应该对用户透明

## 手动模式 vs 自动模式

### 用户交互（简洁）

```bash
# 自动检测（无需指定ROI）
screen-airdrop-receiver

# 手动拉选ROI（交互式）
screen-airdrop-receiver --roi-interactive

# 手动指定ROI（命令行）
screen-airdrop-receiver --roi 100,100,800,600
```

### 内部实现差异

| 特性 | 手动模式 | 自动模式 |
|------|---------|---------|
| **ROI来源** | 用户指定，固定不变 | 动态跟踪，成功后更新 |
| **Capture** | 裁剪到ROI | 全屏 |
| **roi_only** | True（强制只在ROI内） | False（允许fallback） |
| **manual_strict** | True（禁用fallback） | False（启用fallback） |
| **track→full fallback** | ❌ 禁用 | ✅ 启用 |
| **locator engine fallback** | auto（new→legacy） | auto（new→legacy） |
| **性能** | 🚀 极快（小区域） | 🐢 较慢（全屏） |
| **鲁棒性** | ⚠️ 低（ROI偏移即失败） | ✅ 高（多重fallback） |

**关键优化（必须保留）：**
- 手动模式：capture阶段裁剪，避免全屏处理
- 手动模式：roi_only=True，只在ROI内查找
- 手动模式：manual_strict=True，禁用fallback
- 自动模式：动态ROI跟踪，成功后更新track_roi

## 重构方案

### 阶段1: 创建FrameLocator类

```python
# src/screen_airdrop/receiver/frame_locator.py

class FrameLocator:
    """Stateful frame locator with ROI tracking and engine selection."""

    def __init__(
        self,
        *,
        config: LocatorConfig,
        engine: str = "auto",  # "new" | "legacy" | "auto"
        initial_roi: Optional[Tuple[int, int, int, int]] = None,
        fixed_roi: bool = False,  # 手动模式：固定ROI不更新
    ):
        self._config = config
        self._engine = engine
        self._initial_roi = initial_roi
        self._track_roi = initial_roi
        self._fixed_roi = fixed_roi

    def locate(
        self,
        frame: np.ndarray,
    ) -> LocateResult | LocateError:
        """Run locator with current ROI tracking state."""
        search_roi = self._track_roi or self._initial_roi

        if self._engine == "new":
            return locate_frame(frame, search_roi, self._config)
        elif self._engine == "legacy":
            return locate_frame_legacy(frame, search_roi, self._config)
        else:  # auto
            result = locate_frame(frame, search_roi, self._config)
            if isinstance(result, LocateError) or result.quality.confidence < self._config.confidence_threshold:
                return locate_frame_legacy(frame, search_roi, self._config)
            return result

    def update_roi_from_bbox(self, bbox: Tuple[int, int, int, int]) -> None:
        """Update tracking ROI from successful detection bbox."""
        if self._fixed_roi:
            # 手动模式：固定ROI不更新
            return

        # 自动模式：动态更新
        bx, by, bw, bh = bbox
        margin = max(24, min(96, int(min(bw, bh) * 0.10)))
        x1 = max(0, bx - margin)
        y1 = max(0, by - margin)
        self._track_roi = (x1, y1, bw + 2*margin, bh + 2*margin)

    def reset_roi(self) -> None:
        """Reset to initial ROI."""
        self._track_roi = self._initial_roi
```

### 阶段2: 简化Decoder接口

```python
# Decoder不再需要locator_engine参数
class BasicProtocolDecoder:
    def __init__(
        self,
        grid_w: int,
        grid_h: int,
        guard_band: int,
        corner_size: int,
    ):
        # 移除: locator_engine, locator_confidence_threshold
        pass

    def decode_from_locate_result(
        self,
        locate_result: LocateResult,
    ) -> DecodedFrame:
        """Decode from pre-computed locate result."""
        # 直接使用locate_result.modules进行解码
        # 不再调用locator
        pass
```

### 阶段3: 增强GeometryTracker

```python
# src/screen_airdrop/receiver/runtime/geometry_tracker.py

class GeometryTracker:
    """Enhanced geometry tracker with full locator state machine."""

    def __init__(
        self,
        *,
        locator: FrameLocator,
        confidence_threshold: float = 0.55,
        fail_reacquire_threshold: int = 5,
    ):
        self._locator = locator
        self._confidence_threshold = confidence_threshold
        self._fail_reacquire_threshold = fail_reacquire_threshold

        self._lock_mode = "acquire"  # "acquire" | "locked"
        self._locked_geometry: Optional[GeometryState] = None
        self._fail_streak = 0
        self._geometry_age = 0

    def should_use_geometry_reuse(self) -> bool:
        """Check if should use geometry reuse (locked mode)."""
        return self._lock_mode == "locked" and self._locked_geometry is not None

    def get_locked_geometry(self) -> Optional[GeometryState]:
        """Get locked geometry for reuse."""
        return self._locked_geometry if self._lock_mode == "locked" else None

    def locate_frame(self, frame: np.ndarray) -> LocateResult | LocateError:
        """Run locator (only in acquire mode)."""
        if self._lock_mode != "acquire":
            raise RuntimeError("Cannot locate in locked mode")
        return self._locator.locate(frame)

    def record_success(
        self,
        *,
        geometry: Optional[GeometryState],
        bbox: Tuple[int, int, int, int],
    ) -> None:
        """Record successful decode."""
        self._fail_streak = 0

        if geometry is not None and geometry.quality_score >= self._confidence_threshold:
            # Lock geometry
            self._lock_mode = "locked"
            self._locked_geometry = geometry
            self._geometry_age = 0

        # Update ROI tracking
        self._locator.update_roi_from_bbox(bbox)

    def record_failure(self) -> bool:
        """Record failed decode. Returns True if should reacquire."""
        self._fail_streak += 1

        if self._lock_mode == "locked" and self._fail_streak >= self._fail_reacquire_threshold:
            # Trigger reacquire
            self._lock_mode = "acquire"
            self._locked_geometry = None
            self._geometry_age = 0
            self._fail_streak = 0
            self._locator.reset_roi()
            return True

        return False
```

### 阶段4: 简化CLI参数

**保留的用户参数（2个）：**
```bash
--roi x,y,w,h              # 可选：手动指定ROI
--roi-interactive          # 可选：交互式拉选ROI
```

**隐藏的内部参数（使用智能默认值）：**
```python
--roi-mode                 # 隐藏：自动推断（有ROI→manual，无ROI→auto）
--manual-roi-pad-px        # 隐藏：默认0
--manual-max-retries       # 隐藏：默认1
--auto-fail-threshold      # 隐藏：默认5
--detect-mode              # 隐藏：自动切换（track/full）
--track-margin-px          # 隐藏：默认96
--locator-engine           # 隐藏：默认auto
--locator-confidence-threshold  # 隐藏：默认0.55
```

**智能默认行为：**
```python
if args.roi or args.roi_interactive:
    # 手动模式（高效模型）
    mode = "manual"
    roi_only = True
    manual_strict = True
    fixed_roi = True
    capture_region = roi  # capture阶段裁剪
else:
    # 自动模式（鲁棒模型）
    mode = "auto"
    roi_only = False
    manual_strict = False
    fixed_roi = False
    # 动态ROI跟踪 + 多重fallback
```

### 阶段5: 重构Worker逻辑

```python
# src/screen_airdrop/receiver/runtime/workers.py

def _decode_worker_main(...):
    # 创建locator和tracker
    locator = FrameLocator(
        config=LocatorConfig(...),
        engine="auto",  # 默认auto
        initial_roi=initial_search_roi,
        fixed_roi=is_manual_mode,
    )
    tracker = GeometryTracker(
        locator=locator,
        confidence_threshold=0.55,
        fail_reacquire_threshold=5,
    )
    decoder = make_decoder(protocol, grid_w, grid_h, ...)

    while not stopped:
        assignment = assignment_queue.get()
        frame = get_frame_from_slot(assignment.slot_name)

        try:
            if tracker.should_use_geometry_reuse():
                # 使用locked geometry直接解码
                geometry = tracker.get_locked_geometry()
                decoded = decoder.decode_with_geometry(frame, geometry)
            else:
                # 运行locator
                locate_result = tracker.locate_frame(frame)
                if isinstance(locate_result, LocateError):
                    raise ValueError(f"Locator failed: {locate_result.fail_reason}")

                # 解码
                decoded = decoder.decode_from_locate_result(locate_result)

            # 成功
            tracker.record_success(
                geometry=extract_geometry_from_meta(decoded.meta),
                bbox=decoded.meta.det_bbox,
            )
            result_queue.put(DecodeCompletion(success=True, ...))

        except Exception as exc:
            # 失败
            should_reacquire = tracker.record_failure()
            result_queue.put(DecodeCompletion(success=False, ...))
```

## 实施步骤

1. ✅ 恢复旧的pipeline.py
2. ⬜ 创建`frame_locator.py`，实现FrameLocator类
3. ⬜ 重构`locator_basic.py`，确保locate_frame/locate_frame_legacy是纯函数
4. ⬜ 增强`geometry_tracker.py`，集成FrameLocator
5. ⬜ 简化decoder接口，移除locator相关参数
6. ⬜ 简化CLI参数，隐藏内部参数
7. ⬜ 重构`workers.py`，使用新的locator/tracker架构
8. ⬜ 更新测试用例
9. ⬜ 性能验证

## 预期收益

1. **职责清晰**
   - Locator: 纯函数，只做几何定位
   - FrameLocator: ROI跟踪和engine选择
   - GeometryTracker: 状态机管理
   - Decoder: 纯粹解码

2. **用户体验**
   - 只需2个参数：`--roi` 和 `--roi-interactive`
   - 内部参数对用户透明
   - 自动选择最优策略

3. **可测试性**
   - 每个组件可以独立测试
   - 状态机逻辑可以单元测试

4. **可复用性**
   - FrameLocator可以在其他场景使用
   - GeometryTracker不依赖特定的runtime实现

5. **可维护性**
   - 状态转换逻辑集中在GeometryTracker
   - 不再分散在pipeline/decoder/runtime中

6. **性能优化保留**
   - 手动模式：capture裁剪、固定ROI、无fallback
   - 自动模式：动态跟踪、多重fallback
