"""
Unit tests for the cancellation controller.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.executor.cancellation import CancellationController


class TestCancellationController:
    """Tests for CancellationController."""

    def test_initial_state(self) -> None:
        """Test that initial state is not cancelled."""
        lock = threading.Lock()
        controller = CancellationController(lock)

        assert controller.should_stop() is False
        assert controller.is_cancelled() is False
        assert controller.is_cancelled("any-node") is False

    def test_cancel_all(self) -> None:
        """Test global cancellation."""
        lock = threading.Lock()
        controller = CancellationController(lock)

        controller.cancel_all()

        assert controller.should_stop() is True
        assert controller.is_cancelled() is True
        assert controller.is_cancelled("any-node") is True

    def test_cancel_specific_node(self) -> None:
        """Test per-node cancellation."""
        lock = threading.Lock()
        controller = CancellationController(lock)

        controller.cancel_node("node-1")

        assert controller.should_stop() is False  # Global not triggered
        assert controller.is_cancelled() is False  # No node-id check
        assert controller.is_cancelled("node-1") is True
        assert controller.is_cancelled("node-2") is False

    def test_reset(self) -> None:
        """Test that reset clears all cancellation state."""
        lock = threading.Lock()
        controller = CancellationController(lock)

        controller.cancel_all()
        controller.cancel_node("node-1")
        controller.reset()

        assert controller.should_stop() is False
        assert controller.is_cancelled("node-1") is False

    def test_register_and_clear_running(self) -> None:
        """Test running task registration."""
        lock = threading.Lock()
        controller = CancellationController(lock)

        # Create a mock future
        loop = asyncio.new_event_loop()
        future = loop.create_future()

        controller.register_running("node-1", future)
        controller.clear_running("node-1")

        # Should not raise
        controller.clear_running("nonexistent")

        loop.close()

    def test_cancel_node_cascades_to_loop_body(self) -> None:
        """Cancelling a loop node should cascade to its body nodes."""
        lock = threading.Lock()
        controller = CancellationController(lock)

        controller.register_loop_body("loop-1", {"body-a", "body-b"})
        assert controller.is_cancelled("body-a") is False

        controller.cancel_node("loop-1")

        assert controller.is_cancelled("loop-1") is True
        assert controller.is_cancelled("body-a") is True
        assert controller.is_cancelled("body-b") is True
        # Unrelated node remains unaffected
        assert controller.is_cancelled("other") is False

    def test_reset_clears_loop_body_relationships(self) -> None:
        """Reset must clear loop-body bookkeeping so old runs don't leak."""
        lock = threading.Lock()
        controller = CancellationController(lock)

        controller.register_loop_body("loop-1", {"body-a"})
        controller.cancel_node("loop-1")
        controller.reset()

        # After reset, body-a should not still be cancelled via parent loop
        assert controller.is_cancelled("body-a") is False
        assert controller.is_cancelled("loop-1") is False

    def test_concurrent_cancel_and_check_does_not_raise(self) -> None:
        """Lots of threads cancelling/checking must not corrupt state."""
        lock = threading.Lock()
        controller = CancellationController(lock)

        stop = threading.Event()
        errors: list = []

        def cancel_loop() -> None:
            i = 0
            while not stop.is_set():
                try:
                    controller.cancel_node(f"node-{i % 50}")
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)
                i += 1

        def check_loop() -> None:
            while not stop.is_set():
                try:
                    controller.is_cancelled(f"node-{0}")
                    controller.is_cancelled(f"node-{25}")
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)

        threads = [
            threading.Thread(target=cancel_loop),
            threading.Thread(target=cancel_loop),
            threading.Thread(target=check_loop),
            threading.Thread(target=check_loop),
        ]
        for t in threads:
            t.start()
        # Run for a short window
        import time as _time
        _time.sleep(0.2)
        stop.set()
        for t in threads:
            t.join(timeout=2.0)

        assert errors == []
