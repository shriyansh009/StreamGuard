"""StreamGuard background worker package.

Contains the Redis Stream consumer worker and WorkerManager lifecycle orchestrator.
"""

from app.worker.stream_consumer import StreamConsumer
from app.worker.worker_manager import WorkerManager

__all__ = ["StreamConsumer", "WorkerManager"]
