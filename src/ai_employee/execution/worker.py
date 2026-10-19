"""Worker process: claim a turn, run it with a durable checkpoint, record the outcome.

Run with `python -m ai_employee.execution.worker`. Any number may run side by side.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import signal
import socket
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import FrameType
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from ai_employee.agent import TurnResult, run_turn
from ai_employee.execution import queue
from ai_employee.execution.checkpointer import open_checkpointer
from ai_employee.observability import configure_logging, request_context

logger = logging.getLogger(__name__)

RunTurn = Callable[..., TurnResult]


class Worker:
    def __init__(
        self,
        *,
        worker_id: str | None = None,
        lease: timedelta = timedelta(seconds=60),
        poll_interval: float = 1.0,
        run: RunTurn = run_turn,
    ) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.lease = lease
        self.poll_interval = poll_interval
        self.run = run
        self.stopping = threading.Event()

    @contextmanager
    def _heartbeat(self, task_id: uuid.UUID) -> Iterator[None]:
        """Renew the lease while the turn runs, so a live worker is never presumed dead."""
        done = threading.Event()

        def beat() -> None:
            while not done.wait(self.lease.total_seconds() / 3):
                if not queue.renew(task_id, self.worker_id, self.lease):
                    logger.warning("lost lease on task %s", task_id)
                    return

        thread = threading.Thread(target=beat, name=f"heartbeat-{task_id}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join()

    def run_once(self, checkpointer: BaseCheckpointSaver[Any] | None) -> bool:
        """Process at most one task. Returns whether one was claimed."""
        task = queue.claim_next(self.worker_id, self.lease)
        if task is None:
            return False

        with request_context(task.correlation_id):
            if task.attempts > queue.MAX_ATTEMPTS:
                logger.error("task %s abandoned after %d attempts", task.id, task.attempts - 1)
                queue.fail(task.id, self.worker_id, "abandoned: worker stopped", retry=False)
                return True

            logger.info("task %s claimed (attempt %d)", task.id, task.attempts)
            try:
                with self._heartbeat(task.id):
                    result = self.run(
                        queue.context_for(task),
                        task.message,
                        checkpointer=checkpointer,
                        thread_id=str(task.id),
                    )
            except Exception as exc:
                retry = task.attempts < queue.MAX_ATTEMPTS
                logger.exception("task %s failed (retry=%s)", task.id, retry)
                queue.fail(task.id, self.worker_id, f"{type(exc).__name__}: {exc}", retry=retry)
                return True

            queue.complete(task.id, self.worker_id, dataclasses.asdict(result))
            logger.info("task %s succeeded", task.id)
        return True

    def run_forever(self) -> None:
        logger.info("worker %s started", self.worker_id)
        with open_checkpointer() as checkpointer:
            while not self.stopping.is_set():
                if not self.run_once(checkpointer):
                    self.stopping.wait(self.poll_interval)
        logger.info("worker %s stopped", self.worker_id)

    def stop(self, signum: int, _frame: FrameType | None) -> None:
        # Finish the current turn; a killed worker is recovered by lease expiry instead.
        logger.info("signal %d: stopping after the current task", signum)
        self.stopping.set()


def main() -> None:
    configure_logging()
    worker = Worker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
