"""Single-producer shared memory blocks; queues carry descriptions, never point arrays."""

from collections import deque
from multiprocessing import shared_memory
import queue

import numpy as np


class SaveBufferFull(RuntimeError):
    pass


class SharedPointCloudPool:
    def __init__(self, memory, block_bytes, block_count):
        self.memory = memory
        self.descriptor = {"name": memory.name, "block_bytes": block_bytes,
                           "block_count": block_count, "dtype": "float64", "columns": 3}
        self._closed = False

    @classmethod
    def create(cls, block_bytes, block_count):
        block_bytes = int(block_bytes) // 24 * 24
        block_count = int(block_count)
        if block_bytes < 24 or block_count < 2:
            raise ValueError("Point cloud pool requires at least two blocks, each holding an XYZ point")
        memory = shared_memory.SharedMemory(create=True, size=block_bytes * block_count)
        return cls(memory, block_bytes, block_count)

    def close(self):
        if not self._closed:
            self.memory.close()
            try:
                self.memory.unlink()
            except FileNotFoundError:
                pass
            self._closed = True


def block_view(memory, descriptor, block):
    slot = int(block["slot_id"])
    count = int(block["count"])
    if not 0 <= slot < descriptor["block_count"] or not 0 < count <= descriptor["block_bytes"] // 24:
        raise ValueError("Invalid shared point cloud block")
    return np.ndarray((count, 3), dtype=np.float64, buffer=memory.buf,
                      offset=slot * descriptor["block_bytes"])


def read_blocks(descriptor, blocks):
    """Independent snapshots for tools/tests; the writer uses block_view without this copy."""
    memory = shared_memory.SharedMemory(name=descriptor["name"])
    try:
        for block in blocks:
            yield block_view(memory, descriptor, block).copy()
    finally:
        memory.close()


class PointCloudSaveBuffer:
    def __init__(self, descriptor, ack_queue):
        self.descriptor = descriptor
        self.memory = shared_memory.SharedMemory(name=descriptor["name"])
        self.ack_queue = ack_queue
        self.capacity = descriptor["block_bytes"] // 24
        self._free = deque(range(descriptor["block_count"]))
        self._generations = [0] * descriptor["block_count"]
        self._channels = {}
        self._pending = {}

    @property
    def free_blocks(self):
        return len(self._free)

    @property
    def has_data(self):
        return bool(self._channels)

    @property
    def pending_jobs(self):
        return len(self._pending)

    def poll_acks(self):
        while True:
            try:
                self.acknowledge(self.ack_queue.get_nowait())
            except queue.Empty:
                return

    def acknowledge(self, ack):
        job_id = ack.get("job_id")
        expected = self._pending.get(job_id)
        if expected is None or ack.get("blocks") != expected:
            return False
        for block in expected:
            if self._generations[block["slot_id"]] != block["generation"]:
                return False
        self._free.extend(block["slot_id"] for block in expected)
        del self._pending[job_id]
        return True

    def append(self, channel, points):
        points = np.asarray(points, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError("Saved point cloud must have shape (N, 3)")
        if not len(points):
            return
        self.poll_acks()
        blocks = self._channels.get(channel, [])
        available = self.capacity - blocks[-1]["count"] if blocks else 0
        needed = (max(0, len(points) - available) + self.capacity - 1) // self.capacity
        if needed > len(self._free):
            raise SaveBufferFull(f"Point cloud save buffer exhausted: need {needed} blocks, "
                                 f"free {len(self._free)}, pending jobs {len(self._pending)}")
        blocks = self._channels.setdefault(channel, [])
        cursor = 0
        while cursor < len(points):
            if not blocks or blocks[-1]["count"] == self.capacity:
                slot = self._free.popleft()
                self._generations[slot] += 1
                blocks.append({"slot_id": slot, "generation": self._generations[slot], "count": 0})
            block = blocks[-1]
            size = min(self.capacity - block["count"], len(points) - cursor)
            view = np.ndarray((self.capacity, 3), dtype=np.float64, buffer=self.memory.buf,
                              offset=block["slot_id"] * self.descriptor["block_bytes"])
            view[block["count"]:block["count"] + size] = points[cursor:cursor + size]
            block["count"] += size
            cursor += size

    def seal(self, job_id, **metadata):
        if job_id in self._pending:
            raise ValueError("Duplicate save job id")
        job = {**metadata, "job_id": job_id, "channels": self._channels}
        self._pending[job_id] = [dict(block) for blocks in self._channels.values() for block in blocks]
        self._channels = {}
        return job

    def release_unsaved(self):
        self._free.extend(block["slot_id"] for blocks in self._channels.values() for block in blocks)
        self._channels = {}

    def close(self):
        self.memory.close()
