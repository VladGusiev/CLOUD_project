from collections import deque


class MetricWindow:
    """Sliding window that smooths metric samples to avoid reacting to single spikes."""

    def __init__(self, size: int = 3):
        self._window = deque(maxlen=size)
        self._size = size

    def add(self, value: float) -> None:
        self._window.append(value)

    def average(self) -> float:
        if not self._window:
            return 0.0
        return sum(self._window) / len(self._window)

    def is_full(self) -> bool:
        return len(self._window) == self._size

    def values(self) -> list[float]:
        return list(self._window)

    def __len__(self) -> int:
        return len(self._window)
