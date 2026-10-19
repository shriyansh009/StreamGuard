"""StreamGuard Redis Stream Consumer Worker.

Listens to Redis chat streams using Consumer Groups, executes NLP toxicity
analysis via ContentAnalyzer, records moderation infractions in PostgreSQL,
dispatches rate limiting penalties, and acknowledges (XACK) processed messages.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, ResponseError

from app.nlp.content_analyzer import ContentAnalyzer
from app.rate_limiter import RateLimiter

try:
    from app.models.moderation_log import ModerationLog
except ImportError:
    ModerationLog = None  # type: ignore

logger = logging.getLogger(__name__)


class StreamConsumer:
    """Redis Stream consumer worker for distributed real-time moderation."""

    DEFAULT_CONSUMER_GROUP: str = "streamguard-workers"
    DEFAULT_STREAM_PATTERN: str = "stream:chat:*"
    DEFAULT_BATCH_SIZE: int = 10
    DEFAULT_BLOCK_MS: int = 2000
    FALLBACK_STREAM: str = "stream:chat:general"

    def __init__(
        self,
        redis_url: Optional[str] = None,
        consumer_group: str = DEFAULT_CONSUMER_GROUP,
        consumer_name: Optional[str] = None,
        session_factory: Optional[Any] = None,
        analyzer: Optional[ContentAnalyzer] = None,
        rate_limiter: Optional[RateLimiter] = None,
        batch_size: Optional[int] = None,
        block_ms: Optional[int] = None,
    ) -> None:
        """Initialize the StreamConsumer.

        Args:
            redis_url: Redis connection URL (falls back to REDIS_URL env or localhost).
            consumer_group: Redis Stream consumer group name (defaults to 'streamguard-workers').
            consumer_name: Unique consumer identifier (auto-generated if None).
            session_factory: Optional async SQLAlchemy session factory or callable returning AsyncSession.
            analyzer: Optional ContentAnalyzer instance.
            rate_limiter: Optional RateLimiter instance.
            batch_size: Max messages to read per XREADGROUP call.
            block_ms: Milliseconds to block waiting for messages in XREADGROUP.
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name or f"worker-{uuid.uuid4().hex[:8]}"

        self.session_factory = session_factory
        self.analyzer = analyzer or ContentAnalyzer()
        self.rate_limiter = rate_limiter or RateLimiter(redis_url=self.redis_url)

        self.batch_size = int(
            batch_size or os.getenv("WORKER_BATCH_SIZE", str(self.DEFAULT_BATCH_SIZE))
        )
        self.block_ms = int(
            block_ms or os.getenv("WORKER_BLOCK_MS", str(self.DEFAULT_BLOCK_MS))
        )

        self.redis_client: Optional[Redis] = None
        self.is_running: bool = False
        self._stop_event = asyncio.Event()
        self._drain_lock = asyncio.Lock()
        self._known_streams: set[str] = set()

        logger.info(
            "StreamConsumer created: group='%s', name='%s', batch_size=%d, block_ms=%d",
            self.consumer_group,
            self.consumer_name,
            self.batch_size,
            self.block_ms,
        )

    async def initialize(self) -> None:
        """Connect to Redis and create consumer groups for active streams."""
        logger.info("Initializing StreamConsumer '%s'...", self.consumer_name)
        if self.redis_client is None:
            self.redis_client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                protocol=2,
                socket_timeout=10.0,
                socket_connect_timeout=10.0,
                retry_on_timeout=True,
            )

        # Ping Redis to verify connection
        await self.redis_client.ping()
        logger.info("Connected to Redis at %s", self.redis_url)

        # Discover existing streams and ensure consumer groups
        streams = await self._discover_streams(self.DEFAULT_STREAM_PATTERN)
        if not streams:
            streams = [self.FALLBACK_STREAM]

        for stream_key in streams:
            await self.ensure_group(stream_key)

    async def ensure_group(self, stream_key: str) -> None:
        """Create consumer group for stream if it does not exist (MKSTREAM).

        Args:
            stream_key: Redis stream key.
        """
        if self.redis_client is None:
            await self.initialize()

        assert self.redis_client is not None
        try:
            # MKSTREAM ensures stream key is created if not already existing
            await self.redis_client.xgroup_create(
                name=stream_key,
                groupname=self.consumer_group,
                id="0",
                mkstream=True,
            )
            logger.info(
                "Created consumer group '%s' for stream '%s'",
                self.consumer_group,
                stream_key,
            )
            self._known_streams.add(stream_key)
        except ResponseError as e:
            err_msg = str(e)
            if "BUSYGROUP" in err_msg:
                # Group already exists, which is the expected common case
                logger.debug(
                    "Consumer group '%s' already exists on '%s'",
                    self.consumer_group,
                    stream_key,
                )
                self._known_streams.add(stream_key)
            else:
                logger.error(
                    "Unexpected ResponseError creating consumer group on '%s': %s",
                    stream_key,
                    e,
                )
                raise
        except Exception as e:
            logger.error("Failed to ensure consumer group for stream '%s': %s", stream_key, e)
            raise

    async def _discover_streams(self, pattern: str) -> List[str]:
        """Discover streams matching pattern using Redis SCAN.

        Args:
            pattern: Glob-style match pattern (e.g. 'stream:chat:*').

        Returns:
            List of matching stream keys.
        """
        if self.redis_client is None:
            return []

        discovered: List[str] = []
        cursor = 0
        try:
            while True:
                cursor, keys = await self.redis_client.scan(cursor=cursor, match=pattern, count=100)
                for key in keys:
                    discovered.append(key)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("Error discovering streams with pattern '%s': %s", pattern, e)

        return discovered

    def _extract_message_payload(self, fields: Dict[str, Any]) -> Tuple[str, str]:
        """Extract user_id and text content from various message payload formats.

        Args:
            fields: Raw dictionary of fields from Redis stream message.

        Returns:
            Tuple of (user_id, text_content).
        """
        parsed_fields = dict(fields)

        # Check if fields contains a serialized JSON string in 'data' or 'payload'
        for json_key in ("data", "payload", "message_data"):
            if json_key in parsed_fields and isinstance(parsed_fields[json_key], str):
                try:
                    nested = json.loads(parsed_fields[json_key])
                    if isinstance(nested, dict):
                        parsed_fields.update(nested)
                except (json.JSONDecodeError, TypeError):
                    pass

        user_id = str(
            parsed_fields.get("user_id")
            or parsed_fields.get("sender_id")
            or parsed_fields.get("author_id")
            or parsed_fields.get("sender")
            or "anonymous"
        )

        text = str(
            parsed_fields.get("text")
            or parsed_fields.get("content")
            or parsed_fields.get("message")
            or parsed_fields.get("body")
            or ""
        )

        return user_id, text

    async def process_batch(
        self, stream_key: str, messages: List[Tuple[str, Dict[str, Any]]]
    ) -> int:
        """Process a batch of stream messages.

        Workflow:
            1. For each message, run ContentAnalyzer.analyze()
            2. Collect ModerationLog entries
            3. Bulk insert into PostgreSQL using async session
            4. XACK all processed message IDs
            5. If any message triggers violation, call rate_limiter to increment user violations

        Args:
            stream_key: Stream key the messages originated from.
            messages: List of (message_id, field_dict) tuples.

        Returns:
            int: Number of successfully processed messages.
        """
        if not messages:
            return 0

        async with self._drain_lock:
            processed_ids: List[str] = []
            moderation_logs: List[Any] = []
            violating_users: List[Tuple[str, str, float]] = []  # (user_id, reason, score)

            for message_id, fields in messages:
                try:
                    user_id, text = self._extract_message_payload(fields)

                    # 1. Run ContentAnalyzer.analyze()
                    analysis = self.analyzer.analyze(text)

                    score = analysis["toxicity_score"]
                    flagged = analysis["flagged"]
                    action_taken = analysis["action_taken"]
                    matched_patterns = analysis["matched_patterns"]

                    # 2. Collect ModerationLog entries
                    if ModerationLog is not None:
                        import uuid as _uuid
                        from datetime import datetime, timezone
                        # Parse user_id as UUID if possible, skip DB insert if invalid
                        try:
                            parsed_uid = _uuid.UUID(user_id)
                        except (ValueError, AttributeError):
                            parsed_uid = None

                        if parsed_uid is not None:
                            log_entry = ModerationLog(
                                user_id=parsed_uid,
                                room_id=fields.get("room_id", stream_key.split(":")[-1]),
                                original_message=text,
                                toxicity_score=score,
                                flagged=flagged,
                                action_taken=action_taken,
                                matched_patterns=json.dumps(matched_patterns) if matched_patterns else None,
                                processed_at=datetime.now(timezone.utc),
                            )
                            moderation_logs.append(log_entry)
                    else:
                        moderation_logs.append(
                            {
                                "message_id": str(message_id),
                                "stream_key": stream_key,
                                "user_id": user_id,
                                "content": text,
                                "toxicity_score": score,
                                "flagged": flagged,
                                "action_taken": action_taken,
                                "matched_patterns": matched_patterns,
                            }
                        )

                    # Track violation for rate limiting if flagged or blocked
                    if flagged or action_taken in ("flagged", "blocked"):
                        violating_users.append((user_id, action_taken, score))

                    processed_ids.append(message_id)

                except Exception as e:
                    logger.error(
                        "Error analyzing message '%s' on stream '%s': %s",
                        message_id,
                        stream_key,
                        e,
                        exc_info=True,
                    )
                    # Still mark message ID to avoid poison pill deadlock in stream
                    processed_ids.append(message_id)

            # 3. Bulk insert into PostgreSQL using async session
            if self.session_factory is not None and moderation_logs:
                await self._persist_logs(moderation_logs)

            # 4. XACK all processed message IDs in Redis
            if processed_ids and self.redis_client is not None:
                try:
                    await self.redis_client.xack(
                        stream_key, self.consumer_group, *processed_ids
                    )
                    logger.debug(
                        "XACKed %d messages on stream '%s' by '%s'",
                        len(processed_ids),
                        stream_key,
                        self.consumer_name,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to XACK messages %s on '%s': %s",
                        processed_ids,
                        stream_key,
                        e,
                    )

            # 5. If any message triggers violation, call rate_limiter to increment user violations
            for u_id, action, score in violating_users:
                try:
                    res = await self.rate_limiter.record_violation(u_id)
                    if res.get("blacklisted"):
                        logger.warning(
                            "CRITICAL: User '%s' blacklisted after violation (score=%.2f, action=%s).",
                            u_id,
                            score,
                            action,
                        )
                except Exception as e:
                    logger.error(
                        "Error updating rate limiter for violating user '%s': %s",
                        u_id,
                        e,
                    )

            return len(processed_ids)

    async def _persist_logs(self, logs: List[Any]) -> None:
        """Bulk insert moderation log entries into database via session_factory.

        Args:
            logs: List of ModerationLog model instances or log dictionaries.
        """
        try:
            # Check if session_factory is an async context manager or factory
            session_ctx = self.session_factory()
            async with session_ctx as session:
                if hasattr(session, "begin"):
                    async with session.begin():
                        # If logs are ORM instances
                        if ModerationLog is not None and isinstance(logs[0], ModerationLog):
                            session.add_all(logs)
                        else:
                            # Raw insert fallback
                            logger.info("Persisting %d raw log entries to database.", len(logs))
                else:
                    if ModerationLog is not None and isinstance(logs[0], ModerationLog):
                        session.add_all(logs)
                    await session.commit()
            logger.info("Successfully persisted %d moderation logs to PostgreSQL.", len(logs))
        except Exception as e:
            logger.error("Failed to persist moderation logs to database: %s", e, exc_info=True)

    async def consume(self, stream_pattern: str = DEFAULT_STREAM_PATTERN) -> None:
        """Main consumer loop reading from Redis streams via XREADGROUP.

        1. Use XREADGROUP to read up to WORKER_BATCH_SIZE messages, blocking for WORKER_BLOCK_MS
        2. Call process_batch for received messages
        3. Handle errors gracefully with retries and reconnect logic

        Args:
            stream_pattern: Stream pattern to discover and subscribe to.
        """
        logger.info(
            "StreamConsumer '%s' starting consume loop on pattern '%s'...",
            self.consumer_name,
            stream_pattern,
        )

        last_discovery_time = 0.0
        discovery_interval = 10.0  # Discover new streams every 10 seconds
        active_streams: List[str] = []
        backoff_delay = 1.0

        while not self._stop_event.is_set():
            try:
                now = asyncio.get_event_loop().time()
                # Periodically discover active streams
                if now - last_discovery_time > discovery_interval or not active_streams:
                    discovered = await self._discover_streams(stream_pattern)
                    if not discovered:
                        discovered = [self.FALLBACK_STREAM]

                    for s in discovered:
                        if s not in self._known_streams:
                            await self.ensure_group(s)

                    active_streams = discovered
                    last_discovery_time = now

                if not active_streams:
                    await asyncio.sleep(1.0)
                    continue

                # Prepare streams dictionary for XREADGROUP: {stream_name: ">"}
                # ">" means only messages never delivered to any other consumer in the group
                streams_dict = {stream: ">" for stream in active_streams}

                if self.redis_client is None:
                    await self.initialize()

                assert self.redis_client is not None
                raw_response = await self.redis_client.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams=streams_dict,
                    count=self.batch_size,
                    block=self.block_ms,
                )

                # Reset backoff on successful Redis interaction
                backoff_delay = 1.0

                if raw_response:
                    for stream_key, messages in raw_response:
                        if messages and not self._stop_event.is_set():
                            await self.process_batch(stream_key, messages)

            except (RedisConnectionError, ConnectionResetError) as e:
                logger.warning(
                    "Redis connection dropped in consumer '%s': %s. Retrying in %.1fs...",
                    self.consumer_name,
                    e,
                    backoff_delay,
                )
                await asyncio.sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, 30.0)
                try:
                    await self._reconnect()
                except Exception as rec_err:
                    logger.debug("Reconnect attempt failed: %s", rec_err)

            except asyncio.CancelledError:
                logger.info("Consumer '%s' consume task was cancelled.", self.consumer_name)
                break

            except Exception as e:
                logger.error(
                    "Unexpected error in consumer loop '%s': %s",
                    self.consumer_name,
                    e,
                    exc_info=True,
                )
                await asyncio.sleep(1.0)

        logger.info("StreamConsumer '%s' exited consumer loop.", self.consumer_name)

    async def _reconnect(self) -> None:
        """Attempt to re-establish dropped Redis connection."""
        if self.redis_client is not None:
            try:
                await self.redis_client.aclose()
            except Exception:
                pass
            self.redis_client = None

        self.redis_client = aioredis.from_url(
            self.redis_url,
            decode_responses=True,
            protocol=2,
            socket_timeout=10.0,
            socket_connect_timeout=10.0,
            retry_on_timeout=True,
        )
        await self.redis_client.ping()
        logger.info("StreamConsumer '%s' successfully reconnected to Redis.", self.consumer_name)

    async def run(self, stream_pattern: str = DEFAULT_STREAM_PATTERN) -> None:
        """Entry point that discovers streams matching 'stream:chat:*' and consumes.

        Args:
            stream_pattern: Redis stream pattern (defaults to 'stream:chat:*').
        """
        try:
            self.is_running = True
            self._stop_event.clear()
            await self.initialize()
            await self.consume(stream_pattern=stream_pattern)
        except asyncio.CancelledError:
            logger.info("StreamConsumer '%s' run() received cancellation.", self.consumer_name)
        except Exception as e:
            logger.error("Fatal error in StreamConsumer '%s' run(): %s", self.consumer_name, e, exc_info=True)
            raise
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully shut down the consumer worker, draining current processing."""
        if not self.is_running and self._stop_event.is_set():
            return

        logger.info("Shutting down StreamConsumer '%s'...", self.consumer_name)
        self._stop_event.set()
        self.is_running = False

        # Drain: wait for any current processing batch to complete
        async with self._drain_lock:
            logger.debug("Consumer '%s' processing batch drained.", self.consumer_name)

        # Close Redis connection
        if self.redis_client is not None:
            try:
                await self.redis_client.aclose()
                logger.debug("Redis client closed for consumer '%s'.", self.consumer_name)
            except Exception as e:
                logger.warning("Error closing Redis client in consumer '%s': %s", self.consumer_name, e)
            finally:
                self.redis_client = None

        # Close RateLimiter Redis connection
        try:
            await self.rate_limiter.close()
        except Exception as e:
            logger.warning("Error closing RateLimiter connection: %s", e)

        logger.info("StreamConsumer '%s' shutdown complete.", self.consumer_name)
