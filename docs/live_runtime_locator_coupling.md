# Live Runtime Locator耦合分析

## 当前耦合点

### 1. Decoder Worker中的Locator逻辑

**位置：** [workers.py:364-479](src/screen_airdrop/receiver/runtime/workers.py#L364-L479)

```python
def _decode_worker_main(
    *,
    locator_engine: str,  # ← 耦合点1：worker需要知道locator_engine
    locator_confidence_threshold: float,  # ← 耦合点2
):
    decoder = _make_decoder(
        protocol=protocol,
        locator_engine=locator_engine,  # ← 传递给decoder
        locator_confidence_threshold=locator_confidence_threshold,
    )

    while True:
        assignment = assignment_queue.get()

        if protocol == "layered" and geometry_snapshot is not None:
            # Geometry reuse模式
            decoded = decoder.decode_frame_with_geometry(frame, geometry)
        else:
            # Locator模式
            decoded = decoder.decode_frame(
                frame=frame,
                detect_mode="track" if assignment.forced_roi else "full",
                forced_roi=assignment.forced_roi,  # ← 耦合点3：ROI从assignment传入
            )
```

**问题：**
- Worker需要知道locator_engine参数
- Decoder仍然负责locator调用
- ROI通过assignment传递，但没有统一管理

### 2. Coordinator中的ROI管理缺失

**位置：** [coordinator.py:332-345](src/screen_airdrop/receiver/runtime/coordinator.py#L332-L345)

```python
def _build_assignment(self, descriptor: Any) -> DecodeAssignment:
    return DecodeAssignment(
        descriptor=descriptor,
        geometry_generation=self._geometry_tracker.current_generation,
        geometry_state=self._geometry_tracker.current_geometry,
        forced_roi=None,  # ← 问题：ROI硬编码为None！
    )
```

**问题：**
- `forced_roi` 硬编码为 `None`
- 没有ROI跟踪逻辑
- GeometryTracker只管理geometry，不管理ROI

### 3. GeometryTracker不完整

**位置：** [geometry_tracker.py](src/screen_airdrop/receiver/runtime/geometry_tracker.py)

```python
class GeometryTracker:
    def __init__(self, ...):
        self._geometry_state: Optional[GeometryState] = None
        self._lock_mode = "acquire"
        # ← 缺失：没有ROI跟踪
        # ← 缺失：没有FrameLocator集成
```

**问题：**
- 只管理geometry state，不管理ROI
- 没有集成FrameLocator
- 没有locator engine选择逻辑

### 4. Decoder仍然耦合Locator

**位置：** [protocol_adapter_*.py](src/screen_airdrop/receiver/transport/basic/adapter.py)

```python
class BasicProtocolDecoder:
    def __init__(
        self,
        locator_engine: str,  # ← 耦合
        locator_confidence_threshold: float,  # ← 耦合
    ):
        self._locator_engine = locator_engine
        self._locator_confidence_threshold = locator_confidence_threshold

    def decode_frame(self, frame, detect_mode, forced_roi):
        # 内部调用locator
        header, payload, meta = decode_frame_basic(
            frame=frame,
            detect_mode=detect_mode,
            forced_roi=forced_roi,
            locator_engine=self._locator_engine,  # ← 传递
            locator_confidence_threshold=self._locator_confidence_threshold,
        )
```

## 重构方案

### 阶段1: 创建FrameLocator

```python
# src/screen_airdrop/receiver/frame_locator.py

class FrameLocator:
    """Stateful frame locator with ROI tracking."""

    def __init__(
        self,
        *,
        config: LocatorConfig,
        engine: str = "auto",
        initial_roi: Optional[Tuple[int, int, int, int]] = None,
        fixed_roi: bool = False,
    ):
        self._config = config
        self._engine = engine
        self._initial_roi = initial_roi
        self._track_roi = initial_roi
        self._fixed_roi = fixed_roi

    def locate(self, frame: np.ndarray) -> LocateResult | LocateError:
        """Run locator with current ROI."""
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
        """Update tracking ROI."""
        if self._fixed_roi:
            return
        bx, by, bw, bh = bbox
        margin = max(24, min(96, int(min(bw, bh) * 0.10)))
        self._track_roi = (bx - margin, by - margin, bw + 2*margin, bh + 2*margin)

    def get_current_roi(self) -> Optional[Tuple[int, int, int, int]]:
        """Get current tracking ROI."""
        return self._track_roi or self._initial_roi
```

### 阶段2: 增强GeometryTracker

```python
# src/screen_airdrop/receiver/runtime/geometry_tracker.py

class GeometryTracker:
    """Enhanced geometry tracker with FrameLocator integration."""

    def __init__(
        self,
        *,
        locator: FrameLocator,  # ← 新增：集成FrameLocator
        confidence_threshold: float = 0.55,
        lock_fail_reacquire_threshold: int = 5,
    ):
        self._locator = locator  # ← 新增
        self._confidence_threshold = confidence_threshold
        self._lock_fail_reacquire_threshold = lock_fail_reacquire_threshold

        self._geometry_state: Optional[GeometryState] = None
        self._geometry_generation = 0
        self._geometry_fail_streak = 0
        self._lock_mode = "acquire"
        self._locked_geometry_age = 0

    def get_current_roi(self) -> Optional[Tuple[int, int, int, int]]:
        """Get current tracking ROI from locator."""
        return self._locator.get_current_roi()

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
        self._geometry_fail_streak = 0

        if geometry is not None and geometry.quality_score >= self._confidence_threshold:
            self._lock_mode = "locked"
            self._geometry_state = geometry
            self._geometry_age = 0

        # Update ROI tracking
        self._locator.update_roi_from_bbox(bbox)

    def record_failure(self) -> bool:
        """Record failed decode. Returns True if should reacquire."""
        self._geometry_fail_streak += 1

        if self._lock_mode == "locked" and self._geometry_fail_streak >= self._lock_fail_reacquire_threshold:
            self._lock_mode = "acquire"
            self._geometry_state = None
            self._geometry_generation += 1
            self._geometry_fail_streak = 0
            self._locked_geometry_age = 0
            # Note: ROI不重置，保持track_roi
            return True

        return False
```

### 阶段3: 修改Coordinator

```python
# src/screen_airdrop/receiver/runtime/coordinator.py

def _build_assignment(self, descriptor: Any) -> DecodeAssignment:
    """Build decode assignment with current ROI."""
    worker_id = self._next_worker
    self._slot_manager.assign_decode(descriptor, worker_id)

    return DecodeAssignment(
        descriptor=descriptor,
        stream_id=self._stream_id,
        geometry_generation=self._geometry_tracker.current_generation,
        decode_owner=f"decode:{worker_id}",
        dump_requested=descriptor.dump_requested,
        geometry_state=self._geometry_tracker.current_geometry,
        forced_roi=self._geometry_tracker.get_current_roi(),  # ← 修改：从tracker获取ROI
    )

def _handle_decode_completion(self, completion: Any) -> None:
    """Handle successful decode."""
    # ... existing stats ...

    # Update geometry and ROI
    if self._geometry_tracker.lock_mode != "locked" and completion.proposed_geometry_state is not None:
        self._geometry_tracker.propose_update(
            proposed_geometry=completion.proposed_geometry_state,
            decode_quality=completion.decode_quality,
            used_geometry_generation=completion.used_geometry_generation,
        )

    # Extract bbox from meta and update ROI
    bbox = completion.meta.det_bbox  # ← 新增：从meta提取bbox
    self._geometry_tracker.record_success(
        geometry=completion.proposed_geometry_state,
        bbox=bbox,
    )
```

### 阶段4: 简化Decoder Worker

```python
# src/screen_airdrop/receiver/runtime/workers.py

def _decode_worker_main(
    *,
    # 移除: locator_engine, locator_confidence_threshold
    protocol: str,
    grid_w: int,
    grid_h: int,
    guard_band: int,
    corner_size: int,
):
    decoder = _make_decoder(
        protocol=protocol,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=guard_band,
        corner_size=corner_size,
        # 移除: locator_engine, locator_confidence_threshold
    )

    while True:
        assignment = assignment_queue.get()
        frame = frames[descriptor.slot_id]

        try:
            if protocol == "layered" and geometry_snapshot is not None:
                # Geometry reuse
                decoded = decoder.decode_frame_with_geometry(frame, geometry)
            else:
                # Locator模式 - ROI从assignment获取
                decoded = decoder.decode_frame(
                    frame=frame,
                    detect_mode="track" if assignment.forced_roi else "full",
                    forced_roi=assignment.forced_roi,
                )
```

### 阶段5: 简化Decoder接口

```python
# src/screen_airdrop/receiver/transport/basic/adapter.py

class BasicProtocolDecoder:
    def __init__(
        self,
        grid_w: int,
        grid_h: int,
        guard_band: int,
        corner_size: int,
        # 移除: locator_engine, locator_confidence_threshold
    ):
        self._grid_w = grid_w
        self._grid_h = grid_h
        self._guard_band = guard_band
        self._corner_size = corner_size

    def decode_frame(
        self,
        frame: np.ndarray,
        detect_mode: str = "full",
        forced_roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> DecodedFrame:
        """Decode frame. Locator logic moved to FrameLocator."""
        # 调用底层decoder，使用默认locator参数
        header, payload, meta = decode_frame_basic(
            frame=frame,
            detect_mode=detect_mode,
            forced_roi=forced_roi,
            grid_w=self._grid_w,
            grid_h=self._grid_h,
            guard_band=self._guard_band,
            corner_size=self._corner_size,
            roi_only=False,
            manual_strict=False,
            locator_engine="auto",  # ← 硬编码默认值
            locator_confidence_threshold=0.55,  # ← 硬编码默认值
        )
```

### 阶段6: 修改ScreenLiveRuntime初始化

```python
# src/screen_airdrop/receiver/pipeline/live.py

class ScreenLiveRuntime:
    def __init__(
        self,
        *,
        protocol: str,
        grid_w: int,
        grid_h: int,
        guard_band: int,
        corner_size: int,
        # 移除: locator_engine, locator_confidence_threshold
        initial_search_roi: Optional[Tuple[int, int, int, int]] = None,
        fixed_roi: bool = False,  # ← 新增：手动模式标志
    ):
        # 创建FrameLocator
        locator = FrameLocator(
            config=LocatorConfig(
                grid_w=grid_w,
                grid_h=grid_h,
                guard_band=guard_band,
                corner_size=corner_size,
                confidence_threshold=0.55,
            ),
            engine="auto",
            initial_roi=initial_search_roi,
            fixed_roi=fixed_roi,
        )

        # 创建GeometryTracker（集成locator）
        self._geometry_tracker = GeometryTracker(
            locator=locator,
            confidence_threshold=0.55,
            lock_fail_reacquire_threshold=5,
        )
```

## 重构收益

### 1. 职责清晰
- **FrameLocator**: ROI跟踪 + engine选择
- **GeometryTracker**: 状态机管理 + FrameLocator集成
- **Decoder**: 纯粹解码，不管理状态
- **Worker**: 只负责调用decoder，不知道locator细节
- **Coordinator**: 从tracker获取ROI，传递给worker

### 2. 解耦
- Worker不再需要locator_engine参数
- Decoder不再需要locator_engine参数
- ROI管理集中在GeometryTracker中
- Coordinator通过tracker统一管理ROI和geometry

### 3. 可测试性
- FrameLocator可以独立测试ROI跟踪逻辑
- GeometryTracker可以独立测试状态机
- Decoder可以独立测试解码逻辑

### 4. 可维护性
- ROI跟踪逻辑集中在FrameLocator
- 状态机逻辑集中在GeometryTracker
- 不再分散在worker/decoder/coordinator中

## 实施步骤

1. ✅ 恢复旧的pipeline.py
2. ⬜ 创建`frame_locator.py`
3. ⬜ 增强`geometry_tracker.py`，集成FrameLocator
4. ⬜ 修改`coordinator.py`，从tracker获取ROI
5. ⬜ 简化`workers.py`，移除locator参数
6. ⬜ 简化decoder接口，移除locator参数
7. ⬜ 修改`screen_live_runtime.py`初始化
8. ⬜ 更新测试用例
9. ⬜ 性能验证
