"""Standalone production background worker process for RecoverX.

This worker runs as a dedicated service in production environments (e.g. Render background worker),
processing queued Razorpay webhook events, performing settlement-readiness intelligence, and updating cases.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.database.connection import ensure_schema
from app.database.session import SessionLocal
from app.models.webhook_event import WebhookEvent
from app.workers.tasks import process_razorpay_webhook

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [worker] %(message)s",
)
logger = logging.getLogger("recoverx.worker")

SHUTDOWN = False


def signal_handler(signum: int, frame: Any) -> None:
    global SHUTDOWN
    logger.info("Received termination signal %s. Initiating graceful worker shutdown...", signum)
    SHUTDOWN = True


def poll_and_process_pending_events() -> int:
    """Find and process any pending or received webhook events in the database."""
    processed_count = 0
    with SessionLocal() as db:
        try:
            pending_events = db.scalars(
                select(WebhookEvent)
                .where(WebhookEvent.status.in_(["received", "processing_retry"]))
                .order_by(WebhookEvent.received_at.asc())
                .limit(20)
            ).all()

            for event in pending_events:
                if SHUTDOWN:
                    break
                if not event.event_id:
                    continue
                try:
                    logger.info("Worker picking up webhook event %s (%s)", event.event_id, event.event_type)
                    process_razorpay_webhook(event.event_id)
                    processed_count += 1
                except Exception as exc:
                    logger.exception("Worker encountered error processing event %s: %s", event.event_id, exc)
        except Exception as exc:
            logger.error("Database query failed in worker loop: %s", exc)

    return processed_count


async def worker_main() -> None:
    """Main worker loop."""
    logger.info("Starting RecoverX Production Background Worker...")
    ensure_schema()
    logger.info("Database schema verified. Worker is running and polling for events...")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while not SHUTDOWN:
        try:
            processed = await asyncio.to_thread(poll_and_process_pending_events)
            if processed == 0:
                # Sleep briefly between polls if queue is idle
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("Unexpected error in worker main loop: %s", exc)
            await asyncio.sleep(2.0)

    logger.info("RecoverX Background Worker has stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(worker_main())
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user. Exiting.")
        sys.exit(0)

