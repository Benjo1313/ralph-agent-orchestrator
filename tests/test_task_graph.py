"""Tests for TaskGraph Pydantic models."""
import pytest
from datetime import datetime, timezone

from ralph.core.task_graph import Task, TaskStatus, TaskGraph, TaskResult


class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.IN_PROGRESS == "in_progress"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.SKIPPED == "skipped"


class TestTask:
    def test_minimal(self):
        task = Task(id="t1", description="Add dark mode toggle")
        assert task.id == "t1"
        assert task.description == "Add dark mode toggle"
        assert task.status == TaskStatus.PENDING
        assert task.agent is None
        assert task.dependencies == []
        assert task.result is None
        assert task.attempt == 0

    def test_with_dependencies(self):
        task = Task(id="t2", description="Write tests", dependencies=["t1"])
        assert task.dependencies == ["t1"]

    def test_with_agent(self):
        task = Task(id="t3", description="Implement feature", agent="claude_code")
        assert task.agent == "claude_code"

    def test_status_transition(self):
        task = Task(id="t1", description="Do something")
        updated = task.model_copy(update={"status": TaskStatus.IN_PROGRESS, "attempt": 1})
        assert updated.status == TaskStatus.IN_PROGRESS
        assert updated.attempt == 1
        # Original is unchanged (immutability)
        assert task.status == TaskStatus.PENDING

    def test_is_terminal(self):
        done = Task(id="t1", description="x", status=TaskStatus.DONE)
        failed = Task(id="t2", description="x", status=TaskStatus.FAILED)
        skipped = Task(id="t3", description="x", status=TaskStatus.SKIPPED)
        pending = Task(id="t4", description="x", status=TaskStatus.PENDING)
        in_progress = Task(id="t5", description="x", status=TaskStatus.IN_PROGRESS)

        assert done.is_terminal
        assert failed.is_terminal
        assert skipped.is_terminal
        assert not pending.is_terminal
        assert not in_progress.is_terminal


class TestTaskResult:
    def test_success(self):
        r = TaskResult(success=True, output="Done")
        assert r.success
        assert r.output == "Done"
        assert r.error is None

    def test_failure(self):
        r = TaskResult(success=False, error="Agent crashed")
        assert not r.success
        assert r.error == "Agent crashed"

    def test_timestamps_are_utc(self):
        r = TaskResult(success=True)
        assert r.completed_at.tzinfo is not None


class TestTaskGraph:
    def test_empty(self):
        g = TaskGraph(session_id="s1", goal="Add dark mode")
        assert g.tasks == {}
        assert g.session_id == "s1"
        assert g.goal == "Add dark mode"

    def test_add_task(self):
        g = TaskGraph(session_id="s1", goal="Add dark mode")
        t = Task(id="t1", description="Write failing test")
        updated = g.with_task(t)
        assert "t1" in updated.tasks
        # Original unchanged
        assert g.tasks == {}

    def test_update_task(self):
        g = TaskGraph(session_id="s1", goal="Add dark mode")
        t = Task(id="t1", description="Write failing test")
        g = g.with_task(t)
        updated_task = t.model_copy(update={"status": TaskStatus.DONE})
        g2 = g.with_task(updated_task)
        assert g2.tasks["t1"].status == TaskStatus.DONE
        assert g.tasks["t1"].status == TaskStatus.PENDING

    def test_ready_tasks_no_dependencies(self):
        g = TaskGraph(session_id="s1", goal="Test")
        t1 = Task(id="t1", description="A")
        t2 = Task(id="t2", description="B")
        g = g.with_task(t1).with_task(t2)
        ready = g.ready_tasks()
        assert len(ready) == 2

    def test_ready_tasks_with_unmet_dependencies(self):
        g = TaskGraph(session_id="s1", goal="Test")
        t1 = Task(id="t1", description="First")
        t2 = Task(id="t2", description="Second", dependencies=["t1"])
        g = g.with_task(t1).with_task(t2)
        ready = g.ready_tasks()
        # t2 depends on t1 which is pending — only t1 is ready
        ready_ids = {t.id for t in ready}
        assert ready_ids == {"t1"}

    def test_ready_tasks_with_met_dependencies(self):
        g = TaskGraph(session_id="s1", goal="Test")
        t1 = Task(id="t1", description="First", status=TaskStatus.DONE)
        t2 = Task(id="t2", description="Second", dependencies=["t1"])
        g = g.with_task(t1).with_task(t2)
        ready = g.ready_tasks()
        ready_ids = {t.id for t in ready}
        assert ready_ids == {"t2"}

    def test_ready_tasks_excludes_terminal(self):
        g = TaskGraph(session_id="s1", goal="Test")
        t1 = Task(id="t1", description="Done already", status=TaskStatus.DONE)
        g = g.with_task(t1)
        assert g.ready_tasks() == []

    def test_is_complete_all_done(self):
        g = TaskGraph(session_id="s1", goal="Test")
        t1 = Task(id="t1", description="A", status=TaskStatus.DONE)
        t2 = Task(id="t2", description="B", status=TaskStatus.SKIPPED)
        g = g.with_task(t1).with_task(t2)
        assert g.is_complete

    def test_is_complete_false_when_pending(self):
        g = TaskGraph(session_id="s1", goal="Test")
        t1 = Task(id="t1", description="A", status=TaskStatus.DONE)
        t2 = Task(id="t2", description="B", status=TaskStatus.PENDING)
        g = g.with_task(t1).with_task(t2)
        assert not g.is_complete

    def test_is_complete_empty_graph(self):
        g = TaskGraph(session_id="s1", goal="Test")
        assert g.is_complete

    def test_has_failures(self):
        g = TaskGraph(session_id="s1", goal="Test")
        t1 = Task(id="t1", description="A", status=TaskStatus.FAILED)
        g = g.with_task(t1)
        assert g.has_failures

    def test_no_failures(self):
        g = TaskGraph(session_id="s1", goal="Test")
        t1 = Task(id="t1", description="A", status=TaskStatus.DONE)
        g = g.with_task(t1)
        assert not g.has_failures
