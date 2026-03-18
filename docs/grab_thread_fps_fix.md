# Grab Thread FPS Optimization

## Problem

When `--capture-fps` is set to a high value (e.g., 50 fps), the actual capture rate (`cap_fps`) drops significantly and shows instantaneous drops, even with `prep-process=1` and `decode-workers=7`.

## Root Causes

### 1. Original Scheduling Issue (Fixed)

The grab thread was blocking on slot availability, causing it to wait for downstream processing before capturing the next frame.

**Solution**: Restructured to deadline-driven scheduling with non-blocking slot checks.

### 2. Memory Copy Blocking Grab Loop (Fixed)

The grab thread performed two operations synchronously:
- Screen capture: `sct.grab()` - ~17ms
- Memory copy to shared memory: `slot_views[slot_id][...] = bgra[:, :, :3]` - ~4ms

**Total blocking time: 21ms per frame**, limiting max FPS to 46.2.

**Solution**: Offloaded memory copy to separate worker thread.

## Implementation

### Architecture

```
Grab Thread (fast loop):
  1. Check deadline
  2. Try to get slot (non-blocking)
  3. Capture screen: sct.grab() -> shot (~17ms)
  4. Send shot to copy worker queue (~0.1ms)
  5. Immediately start next iteration

Copy Worker Thread (parallel):
  1. Receive shot from queue
  2. Copy shot data to shared memory slot (~4ms)
  3. Send FilledSlotEvent to coordinator
```

### Key Changes

1. **Deadline-driven scheduling** ([workers.py:298-378](../src/screen_airdrop/receiver/runtime/workers.py#L298-L378)):
   - Non-blocking slot check with `get_nowait()`
   - Always capture at deadline, regardless of slot availability
   - When behind schedule, immediately capture next frame

2. **Separate copy worker thread** ([workers.py:280-330](../src/screen_airdrop/receiver/runtime/workers.py#L280-L330)):
   - Dedicated thread for copying to shared memory
   - Runs in parallel with grab loop
   - Queue-based communication (maxsize=20 for backpressure)

3. **Shot object passing**:
   - MSS `ScreenShot` objects can be passed across threads
   - MSS does not reuse buffers, so no immediate copy needed
   - Copy worker handles the actual memory copy

### Performance Impact

**Before optimization**:
- Grab thread blocking time: 21ms (grab + copy)
- Theoretical max FPS: 46.2 fps
- Actual FPS: ~42 fps (with jitter)

**After optimization**:
- Grab thread blocking time: 17ms (grab only)
- Theoretical max FPS: 58.8 fps
- Expected FPS: ~50-55 fps (limited by grab hardware)
- **20% reduction in grab loop latency**

## Hardware Limitations

Even with optimal scheduling and parallel copy, there are fundamental hardware limits:

### Screen Capture Performance
- `sct.grab()` takes ~17ms per frame (MSS + macOS screen capture API)
- This is the primary bottleneck
- Varies 10-30ms depending on system load

### Why Instantaneous FPS Still Varies

1. **Processing time variance**:
   - Screen capture time: 10-30ms (system load dependent)
   - Memory copy time: 3-6ms (memory bandwidth dependent)

2. **System-level interference**:
   - Python GC pauses (1-5ms, occasionally 10-50ms)
   - OS thread scheduling (context switches)
   - Other processes competing for resources

3. **Queue dynamics**:
   - Copy worker may fall behind during bursts
   - Queue backpressure causes frame drops
   - Creates uneven frame timing

## Recommended Settings

For optimal performance:

1. **Match target FPS to hardware capability**:
   - For typical systems: `--capture-fps 30` (safe, consistent)
   - For fast systems: `--capture-fps 45` (good balance)
   - For maximum throughput: `--capture-fps 55` (may see jitter)

2. **Monitor metrics**:
   - `raw_grab_fps`: actual capture rate (should be close to target)
   - `slot_starvation_events`: should be low (< 1% of frames)
   - `capture_grab_time_ms / capture_grab_ops`: average grab time
   - `capture_copy_time_ms / capture_copy_ops`: average copy time

3. **Tune worker counts**:
   - Increase `--decode-workers` if `slot_starvation_events` is high
   - Use `--prep-process 1` for better parallelism
   - Ensure sufficient slot count (automatically calculated)

## Benefits

1. **Higher capture rate**: Grab loop no longer blocked by memory copy
2. **Better parallelism**: Copy happens in parallel with next capture
3. **Reduced latency**: 20% reduction in grab loop blocking time
4. **Consistent timing**: Deadline-driven scheduling maintains target FPS
5. **Better observability**: Separate tracking of grab vs copy time

## Testing

The optimization passes all existing tests:
- [test_grab_nonblocking.py](../tests/unit/test_grab_nonblocking.py) - Slot starvation handling
- [test_grab_stats_separation.py](../tests/unit/test_grab_stats_separation.py) - Stats separation

## Expected Behavior After Fix

With `--capture-fps 50`, `prep-process=1`, and `decode-workers=7`:

- `raw_grab_frames` should be ~50-55 fps (limited by grab hardware, not copy)
- `captured` may be lower (depends on slot availability)
- `slot_starvation_events` will increase when downstream is slow
- Grab loop latency reduced from 21ms to 17ms
- Copy happens in parallel, not blocking next capture

## Future Optimizations

To further improve performance:

1. **Zero-copy capture**: Use shared memory directly with screen capture API (requires MSS changes or platform-specific code)
2. **GPU-accelerated copy**: Use CUDA/Metal for faster memory transfers
3. **Batch processing**: Capture multiple frames before copying (increases latency)
4. **Platform-specific APIs**: Use `CGDisplayCreateImage` (macOS) or `DXGI` (Windows) directly for better performance

