from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.audit_log import AuditLog
from app.models.webhook_event import WebhookEvent

logger = logging.getLogger(__name__)


class DurableWebhookQueue:
    """Durable async worker queue for webhook processing with retry & DLQ support."""

    def __init__(self, max_retries: int = 3, base_backoff_seconds: float = 0.5) -> None:
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._queue: asyncio.Queue[tuple[str, int]] | None = None
        self._worker_task: asyncio.Task | None = None
        self._handler: Callable[[str], None] | None = None

    def set_handler(self, handler: Callable[[str], None]) -> None:
        self._handler = handler

    def _get_queue(self) -> asyncio.Queue[tuple[str, int]]:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    async def start(self) -> None:
        """Start the background consumer loop for the current active event loop."""
        self._queue = asyncio.Queue()
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._consumer_loop())
            logger.info("Durable webhook worker queue consumer started")

    async def stop(self) -> None:
        """Gracefully stop the worker consumer."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass
            self._worker_task = None
        self._queue = None

    async def enqueue(self, event_id: str, retry_count: int = 0) -> None:
        """Enqueue an event ID for durable processing."""
        queue = self._get_queue()
        await queue.put((event_id, retry_count))

    async def _consumer_loop(self) -> None:
        while True:
            try:
                queue = self._get_queue()
                event_id, retry_count = await queue.get()
            except asyncio.CancelledError:
                break

            try:
                if self._handler:
                    await asyncio.to_thread(self._handler, event_id)
            except Exception as exc:
                logger.error("Job processing failed for event %s (attempt %s): %s", event_id, retry_count + 1, exc)
                if retry_count < self.max_retries:
                    backoff = self.base_backoff_seconds * (2 ** retry_count)
                    logger.info("Retrying event %s in %s seconds...", event_id, backoff)
                    await asyncio.sleep(backoff)
                    await self.enqueue(event_id, retry_count + 1)
                else:
                    # Move to Dead Letter Queue (DLQ)
                    logger.error("Event %s exceeded max retries. Moving to Dead Letter Queue.", event_id)
                    self._record_dead_letter(event_id, str(exc))
            finally:
                queue.task_done()

    def _record_dead_letter(self, event_id: str, reason: str) -> None:
        with SessionLocal() as db:
            try:
                event = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
                if event:
                    event.status = "dead_letter"
                    db.add(
                        AuditLog(
                            merchant_id=1,
                            entity_type="webhook_event",
                            entity_id=event_id,
                            event_type="webhook_dead_letter",
                            details=f"Job exceeded max retries and moved to DLQ: {reason[:200]}",
                        )
                    )
                    db.commit()
            except Exception as e:
                db.rollback()
                logger.exception("Failed to record DLQ state for event %s: %s", event_id, e)


# Global durable queue instance
webhook_queue = DurableWebhookQueue()

