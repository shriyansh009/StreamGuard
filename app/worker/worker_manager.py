"""StreamGuard Background Worker Lifecycle Manager.

Orchestrates multiple Redis Stream consumer workers, supervises worker health,
automatically restarts failed workers, and facilitates coordinated graceful shutdowns.
"""

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from app.worker.stream_consumer import StreamConsumer

logger = logging.getLogger(__name__)


class WorkerManager:
    """Supervises and manages the lifecycle of multiple StreamConsumer instances."""

    DEFAULT_NUM_WORKERS: int = 3

    def __init__(
        self,
        redis_url: Optional[str] = None,
        consumer_group: str = StreamConsumer.DEFAULT_CONSUMER_GROUP,
        session_factory: Optional[Any] = None,
        stream_pattern: str = StreamConsumer.DEFAULT_STREAM_PATTERN,
    ) -> None:
        """Initialize the WorkerManager.

        Args:
            redis_url: Optional Redis connection URL.
            consumer_group: Shared consumer group name.
            session_factory: Optional async SQLAlchemy session factory.
            stream_pattern: Stream pattern to subscribe workers to.
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.consumer_group = consumer_group
        self.session_factory = session_factory
        self.stream_pattern = stream_pattern

        self.num_workers: int = self.DEFAULT_NUM_WORKERS
        self.shutdown_event = asyncio.Event()

        # Maps worker_name -> StreamConsumer instance
        self.workers: Dict[str, StreamConsumer] = {}
        # Maps worker_name -> asyncio.Task
        self.worker_tasks: Dict[str, asyncio.Task] = {}
        # Tracks worker slot index -> current worker_name
        self._slot_map: Dict[int, str] = {}
        # Tracks restart counts per slot
        self._restart_counts: Dict[int, int] = {}

        self.monitor_task: Optional[asyncio.Task] = None
        self._is_started: bool = False

    async def start(self, num_workers: int = DEFAULT_NUM_WORKERS) -> None:
        """Start N consumer tasks using asyncio.create_task and launch health supervisor.

        Args:
            num_workers: Number of concurrent consumer workers to spawn (default 3).
        """
        if self._is_started:
            logger.warning("WorkerManager is already started.")
            return

        self.num_workers = num_workers
        self.shutdown_event.clear()
        self._is_started = True

        logger.info(
            "WorkerManager starting %d StreamConsumer workers for group '%s'...",
            self.num_workers,
            self.consumer_group,
        )

        for slot_idx in range(self.num_workers):
            await self._spawn_worker_for_slot(slot_idx)

        # Launch the background health supervisor task
        self.monitor_task = asyncio.create_task(
            self._monitor_workers(),
            name="streamguard-worker-supervisor",
        )
        logger.info("WorkerManager initialized and health supervisor running.")

    async def _spawn_worker_for_slot(self, slot_idx: int) -> StreamConsumer:
        """Create and launch a worker task for a given slot index.

        Args:
            slot_idx: Numeric slot index (0 to num_workers - 1).

        Returns:
            Newly created StreamConsumer.
        """
        worker_id = f"worker-slot{slot_idx}-{uuid.uuid4().hex[:6]}"

        consumer = StreamConsumer(
            redis_url=self.redis_url,
            consumer_group=self.consumer_group,
            consumer_name=worker_id,
            session_factory=self.session_factory,
        )

        self.workers[worker_id] = consumer
        self._slot_map[slot_idx] = worker_id

        task = asyncio.create_task(
            self._run_worker(consumer, slot_idx),
            name=worker_id,
        )
        self.worker_tasks[worker_id] = task

        logger.info("Spawned worker '%s' in slot %d", worker_id, slot_idx)
        return consumer

    async def _run_worker(self, consumer: StreamConsumer, slot_idx: int) -> None:
        """Worker wrapper that catches errors and logs termination.

        Args:
            consumer: StreamConsumer instance to run.
            slot_idx: Assigned slot index.
        """
        try:
            await consumer.run(stream_pattern=self.stream_pattern)
        except asyncio.CancelledError:
            logger.info("Worker '%s' (slot %d) received cancellation.", consumer.consumer_name, slot_idx)
        except Exception as e:
            logger.error(
                "Worker '%s' (slot %d) crashed with error: %s",
                consumer.consumer_name,
                slot_idx,
                e,
                exc_info=True,
            )
            raise
        finally:
            logger.debug("Worker '%s' (slot %d) finished execution.", consumer.consumer_name, slot_idx)

    async def _monitor_workers(self) -> None:
        """Supervise worker tasks, detecting unexpected failures and auto-restarting workers."""
        logger.debug("Worker supervisor task started.")

        while not self.shutdown_event.is_set():
            try:
                # Check health every 2 seconds
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=2.0)
                    # If wait returns True, shutdown was requested
                    break
                except asyncio.TimeoutError:
                    pass

                if self.shutdown_event.is_set():
                    break

                # Inspect all assigned slots
                for slot_idx in range(self.num_workers):
                    worker_id = self._slot_map.get(slot_idx)
                    task = self.worker_tasks.get(worker_id) if worker_id else None

                    needs_restart = False
                    if task is None or task.done():
                        if task and task.done():
                            try:
                                exc = task.exception()
                                if exc:
                                    logger.error(
                                        "Health Check: Worker '%s' in slot %d died with exception: %s",
                                        worker_id,
                                        slot_idx,
                                        exc,
                                    )
                                else:
                                    logger.warning(
                                        "Health Check: Worker '%s' in slot %d exited prematurely.",
                                        worker_id,
                                        slot_idx,
                                    )
                            except asyncio.CancelledError:
                                logger.info(
                                    "Health Check: Worker '%s' in slot %d was cancelled.",
                                    worker_id,
                                    slot_idx,
                                )
                        needs_restart = True

                    if needs_restart and not self.shutdown_event.is_set():
                        # Clean up previous reference
                        if worker_id:
                            self.workers.pop(worker_id, None)
                            self.worker_tasks.pop(worker_id, None)

                        self._restart_counts[slot_idx] = self._restart_counts.get(slot_idx, 0) + 1
                        logger.warning(
                            "Auto-restarting worker in slot %d (restart count: %d)...",
                            slot_idx,
                            self._restart_counts[slot_idx],
                        )
                        await self._spawn_worker_for_slot(slot_idx)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Unexpected error in worker supervisor loop: %s", e, exc_info=True)
                await asyncio.sleep(2.0)

        logger.debug("Worker supervisor loop exited.")

    async def stop(self) -> None:
        """Signal all workers to stop and await graceful shutdown."""
        if not self._is_started:
            return

        logger.info("Initiating graceful shutdown of WorkerManager...")
        self.shutdown_event.set()
        self._is_started = False

        # Cancel the health supervisor
        if self.monitor_task is not None:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
            self.monitor_task = None

        # Signal all consumers to shutdown gracefully
        shutdown_coros = [worker.shutdown() for worker in self.workers.values()]
        if shutdown_coros:
            await asyncio.gather(*shutdown_coros, return_exceptions=True)

        # Await all worker tasks to exit
        tasks = list(self.worker_tasks.values())
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=5.0)
            if pending:
                logger.warning("%d worker tasks did not stop within timeout, cancelling...", len(pending))
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

        self.workers.clear()
        self.worker_tasks.clear()
        self._slot_map.clear()
        logger.info("WorkerManager shutdown complete. All workers stopped.")

    def get_status(self) -> Dict[str, Any]:
        """Return operational status and metrics for the worker pool.

        Returns:
            dict containing health metrics and worker slot information.
        """
        active_count = 0
        slot_details = []

        for slot_idx in range(self.num_workers):
            worker_id = self._slot_map.get(slot_idx)
            task = self.worker_tasks.get(worker_id) if worker_id else None
            is_alive = task is not None and not task.done()
            if is_alive:
                active_count += 1

            slot_details.append(
                {
                    "slot": slot_idx,
                    "worker_id": worker_id,
                    "alive": is_alive,
                    "restarts": self._restart_counts.get(slot_idx, 0),
                }
            )

        return {
            "is_running": self._is_started and not self.shutdown_event.is_set(),
            "target_workers": self.num_workers,
            "active_workers": active_count,
            "slots": slot_details,
        }
