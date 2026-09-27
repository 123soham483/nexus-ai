"""Unit tests for Celery worker tasks (Step 1.14)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.celery_app import celery_app
from app.workers.task_worker import execute_task_worker


def test_task_registered_with_correct_name():
    assert "nexusai.execute_task" in celery_app.tasks
    task = celery_app.tasks["nexusai.execute_task"]
    assert task.name == "nexusai.execute_task"


def test_task_time_limits_configured():
    """Limits come from settings and leave room for a HITL wait (Step 3.4)."""
    from app.config import settings

    task = celery_app.tasks["nexusai.execute_task"]
    assert task.soft_time_limit == settings.TASK_SOFT_TIME_LIMIT
    assert task.time_limit == settings.TASK_TIME_LIMIT
    # A task blocked on human approval must outlast the HITL timeout.
    assert task.soft_time_limit > settings.HITL_TIMEOUT_SECONDS
    assert task.time_limit > task.soft_time_limit


@patch("app.workers.task_worker.asyncio.run")
def test_execute_task_worker_retries_on_exception(mock_run):
    mock_run.side_effect = Exception("transient failure")
    
    # Mock celery task context
    task_self = MagicMock()
    task_self.request.retries = 0
    task_self.max_retries = 3
    task_self.retry = MagicMock(side_effect=Exception("retry called"))

    with pytest.raises(Exception, match="retry called"):
        execute_task_worker.__class__.run(
            task_self,
            task_id="task-123",
            goal="test goal",
            context={},
            tenant_id="tenant-123",
            user_id="user-123"
        )
    
    # Assert retry was called
    task_self.retry.assert_called_once()
    kwargs = task_self.retry.call_args[1]
    assert "exc" in kwargs
    assert kwargs["countdown"] == 1  # 2^0 = 1


@patch("app.workers.task_worker.asyncio.run")
def test_execute_task_worker_exponential_backoff_calculations(mock_run):
    mock_run.side_effect = Exception("transient failure")
    
    # Mock retry count = 2
    task_self = MagicMock()
    task_self.request.retries = 2
    task_self.max_retries = 3
    task_self.retry = MagicMock(side_effect=Exception("retry called"))

    with pytest.raises(Exception, match="retry called"):
        execute_task_worker.__class__.run(
            task_self,
            task_id="task-123",
            goal="test goal",
            context={},
            tenant_id="tenant-123",
            user_id="user-123"
        )
    
    task_self.retry.assert_called_once()
    kwargs = task_self.retry.call_args[1]
    assert kwargs["countdown"] == 4  # 2^2 = 4


@patch("app.workers.task_worker._mark_task_failed", new_callable=AsyncMock)
@patch("app.workers.task_worker.asyncio.run")
def test_execute_task_worker_exhausts_retries_marks_failed(mock_run, mock_mark_failed):
    mock_run.side_effect = Exception("final failure")
    
    # Mock retries = 3 (exhausted)
    task_self = MagicMock()
    task_self.request.retries = 3
    task_self.max_retries = 3
    task_self.retry = MagicMock()

    with pytest.raises(Exception, match="final failure"):
        execute_task_worker.__class__.run(
            task_self,
            task_id="task-123",
            goal="test goal",
            context={},
            tenant_id="tenant-123",
            user_id="user-123"
        )
    
    task_self.retry.assert_not_called()
    
    # We verify the mock mark failed was called with correct arguments
    mock_mark_failed.assert_called_once_with("task-123", "final failure")
