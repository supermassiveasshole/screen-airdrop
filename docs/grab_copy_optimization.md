# Grab Thread Copy Optimization Design

## Current Problem

The grab thread performs two operations synchronously:
1. Screen capture: `sct.grab()` - 17.37ms
2. Memory copy to shared memory: `slot_views[slot_id][...] = bgra[:, :, :3]` - 4.28ms

**Total: 21.65ms per frame**, which blocks the next capture.

## Why We Can't Just Pass `shot` Object

The MSS `ScreenShot` object contains:
- `data: bytearray` - the raw pixel data
- `monitor: Monitor` - metadata

Problems with passing `shot` to another process:
1. `bytearray` is not shared memory - requires pickling
2. Pickling + unpickling 6MB of data is slower than direct copy
3. MSS may reuse internal buffers on next `grab()`

## Proposed Solution: Double-Buffered Copy Worker

### Architecture

```
Grab Thread (fast loop):
  1. grab() -> shot (17ms)
  2. Copy shot.rgb to local buffer (4ms) - FAST, no shared memory
  3. Send (buffer, slot_id) to copy worker queue
  4. Immediately start next grab()

Copy Worker (separate thread):
  1. Receive (buffer, slot_id) from queue
  2. Copy buffer to shared memory slot
  3. Send FilledSlotEvent to coordinator
  4. Return buffer to pool
```

### Benefits

- Grab thread only blocks on `grab()` (17ms), not copy (4ms)
- Copy worker runs in parallel with next grab
- Theoretical max FPS: 1000/17 = **58.8 fps** (vs current 46.2 fps)
- Reduces grab thread latency by 20%

### Implementation Strategy

1. **Buffer Pool**: Pre-allocate N local buffers (numpy arrays)
2. **Copy Queue**: Queue of (buffer, slot_id, metadata) tuples
3. **Copy Worker Thread**: Dedicated thread for copying to shared memory
4. **Buffer Recycling**: Return buffers to pool after copy

### Challenges

1. **Memory overhead**: Need extra buffers (N × 6MB)
   - Solution: Use small pool (2-3 buffers), recycle aggressively

2. **Copy still takes 4ms**: Just moved to different thread
   - But now it's parallel with next grab!

3. **Queue backpressure**: If copy worker is slow, queue fills up
   - Solution: Drop frames when queue is full (already have slot starvation handling)

### Alternative: Zero-Copy with Shared Memory Ring Buffer

Instead of local buffers, use a ring buffer in shared memory:

```
Grab Thread:
  1. grab() -> shot (17ms)
  2. Get next ring buffer slot
  3. Copy shot.rgb to ring buffer (4ms)
  4. Send ring buffer index to copy worker

Copy Worker:
  1. Receive ring buffer index
  2. Copy from ring buffer to slot (4ms)
  3. Mark ring buffer slot as free
```

This still requires two copies, but simplifies buffer management.

### Best Solution: Eliminate Copy in Grab Thread

The real bottleneck is that we must copy `shot.rgb` immediately because MSS may reuse it.

**Ideal solution**: Modify MSS or use lower-level API to grab directly into our buffer.

For macOS, this means using `CGDisplayCreateImage` directly instead of MSS.

## Recommendation

**Phase 1** (Quick win): Implement double-buffered copy worker
- Estimated improvement: 17ms → 17ms grab time (20% reduction in blocking time)
- Complexity: Medium
- Risk: Low

**Phase 2** (Long term): Direct capture to shared memory
- Estimated improvement: 17ms → 15ms (eliminate one copy)
- Complexity: High (platform-specific code)
- Risk: Medium

## Implementation Notes

For Phase 1, the key changes:

1. Add buffer pool in `_grab_thread_main`:
```python
buffer_pool = queue.Queue()
for _ in range(3):
    buffer_pool.put(np.empty((height, width, 3), dtype=np.uint8))
```

2. Start copy worker thread:
```python
copy_queue = queue.Queue(maxsize=10)
copy_thread = threading.Thread(target=_copy_worker, args=(copy_queue, slot_views, ...))
```

3. In grab loop:
```python
shot = sct.grab(monitor)
try:
    buffer = buffer_pool.get_nowait()
    bgra = np.asarray(shot)
    buffer[...] = bgra[:, :, :3]
    copy_queue.put_nowait((buffer, slot_id, generation, ...))
except queue.Empty:
    # No buffer available - drop frame
    pass
```

4. Copy worker:
```python
def _copy_worker(copy_queue, slot_views, ...):
    while True:
        buffer, slot_id, generation, ... = copy_queue.get()
        slot_views[slot_id][...] = buffer
        buffer_pool.put(buffer)  # Recycle
        descriptor_queue.put(FilledSlotEvent(...))
```
