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
