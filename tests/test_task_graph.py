"""Tests for TaskGraph Pydantic models."""
from ralph.core.task_graph import Task, TaskGraph, TaskResult, TaskStatus


class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.IN_PROGRESS == "in_progress"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.ESCALATED == "escalated"
        assert TaskStatus.SKIPPED == "skipped"


class TestTask:
    def test_minimal(self):
        task = Task(id="t1", description="Add dark mode toggle")
        assert task.id == "t1"
        assert task.description == "Add dark mode toggle"
        assert task.task_type is None
        assert task.acceptance_criteria is None
        assert task.retry_guidance is None
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

    def test_with_task_type_and_acceptance_criteria(self):
        task = Task(
            id="t4",
            description="Implement feature",
            task_type="implementation",
            acceptance_criteria="All tests pass",
        )
        assert task.task_type == "implementation"
        assert task.acceptance_criteria == "All tests pass"

    def test_with_retry_guidance(self):
        task = Task(
            id="t5",
            description="Implement feature",
            retry_guidance="Fix the failing tests first",
        )
        assert task.retry_guidance == "Fix the failing tests first"

    def test_status_transition(self):
        task = Task(id="t1", description="Do something")
        updated = task.model_copy(update={"status": TaskStatus.IN_PROGRESS, "attempt": 1})
        assert updated.status == TaskStatus.IN_PROGRESS
        assert updated.attempt == 1
        assert task.status == TaskStatus.PENDING

    def test_is_terminal(self):
        done = Task(id="t1", description="x", status=TaskStatus.DONE)
        failed = Task(id="t2", description="x", status=TaskStatus.FAILED)
        escalated = Task(id="t3", description="x", status=TaskStatus.ESCALATED)
        skipped = Task(id="t4", description="x", status=TaskStatus.SKIPPED)
        pending = Task(id="t5", description="x", status=TaskStatus.PENDING)
        in_progress = Task(id="t6", description="x", status=TaskStatus.IN_PROGRESS)

        assert done.is_terminal
        assert failed.is_terminal
        assert escalated.is_terminal
        assert skipped.is_terminal
        assert not pending.is_terminal
        assert not in_progress.is_terminal


class TestTaskResult:
    def test_success(self):
        result = TaskResult(success=True, output="Done", exit_code=0)
        assert result.success
        assert result.output == "Done"
        assert result.error is None
        assert result.exit_code == 0

    def test_failure(self):
        result = TaskResult(success=False, error="Agent crashed", exit_code=1)
        assert not result.success
        assert result.error == "Agent crashed"
        assert result.exit_code == 1

    def test_timestamps_are_utc(self):
        result = TaskResult(success=True)
        assert result.completed_at.tzinfo is not None


class TestTaskGraph:
    def test_empty(self):
        graph = TaskGraph(session_id="s1", goal="Add dark mode")
        assert graph.tasks == {}
        assert graph.session_id == "s1"
        assert graph.goal == "Add dark mode"

    def test_add_task(self):
        graph = TaskGraph(session_id="s1", goal="Add dark mode")
        task = Task(id="t1", description="Write failing test")
        updated = graph.with_task(task)
        assert "t1" in updated.tasks
        assert graph.tasks == {}

    def test_update_task(self):
        graph = TaskGraph(session_id="s1", goal="Add dark mode")
        task = Task(id="t1", description="Write failing test")
        graph = graph.with_task(task)
        updated_task = task.model_copy(update={"status": TaskStatus.DONE})
        graph2 = graph.with_task(updated_task)
        assert graph2.tasks["t1"].status == TaskStatus.DONE
        assert graph.tasks["t1"].status == TaskStatus.PENDING

    def test_ready_tasks_no_dependencies(self):
        graph = TaskGraph(session_id="s1", goal="Test")
        graph = graph.with_task(Task(id="t1", description="A"))
        graph = graph.with_task(Task(id="t2", description="B"))
        ready = graph.ready_tasks()
        assert len(ready) == 2

    def test_ready_tasks_with_unmet_dependencies(self):
        graph = TaskGraph(session_id="s1", goal="Test")
        graph = graph.with_task(Task(id="t1", description="First"))
        graph = graph.with_task(Task(id="t2", description="Second", dependencies=["t1"]))
        ready_ids = {task.id for task in graph.ready_tasks()}
        assert ready_ids == {"t1"}

    def test_ready_tasks_with_met_dependencies(self):
        graph = TaskGraph(session_id="s1", goal="Test")
        graph = graph.with_task(Task(id="t1", description="First", status=TaskStatus.DONE))
        graph = graph.with_task(Task(id="t2", description="Second", dependencies=["t1"]))
        ready_ids = {task.id for task in graph.ready_tasks()}
        assert ready_ids == {"t2"}

    def test_ready_tasks_excludes_terminal(self):
        graph = TaskGraph(session_id="s1", goal="Test")
        graph = graph.with_task(Task(id="t1", description="Done already", status=TaskStatus.DONE))
        assert graph.ready_tasks() == []

    def test_is_complete_all_done(self):
        graph = TaskGraph(session_id="s1", goal="Test")
        graph = graph.with_task(Task(id="t1", description="A", status=TaskStatus.DONE))
        graph = graph.with_task(Task(id="t2", description="B", status=TaskStatus.SKIPPED))
        assert graph.is_complete

    def test_is_complete_false_when_pending(self):
        graph = TaskGraph(session_id="s1", goal="Test")
        graph = graph.with_task(Task(id="t1", description="A", status=TaskStatus.DONE))
        graph = graph.with_task(Task(id="t2", description="B", status=TaskStatus.PENDING))
        assert not graph.is_complete

    def test_is_complete_empty_graph(self):
        graph = TaskGraph(session_id="s1", goal="Test")
        assert graph.is_complete

    def test_has_failures_for_failed(self):
        graph = TaskGraph(session_id="s1", goal="Test").with_task(
            Task(id="t1", description="A", status=TaskStatus.FAILED)
        )
        assert graph.has_failures

    def test_has_failures_for_escalated(self):
        graph = TaskGraph(session_id="s1", goal="Test").with_task(
            Task(id="t1", description="A", status=TaskStatus.ESCALATED)
        )
        assert graph.has_failures

    def test_no_failures(self):
        graph = TaskGraph(session_id="s1", goal="Test").with_task(
            Task(id="t1", description="A", status=TaskStatus.DONE)
        )
        assert not graph.has_failures
