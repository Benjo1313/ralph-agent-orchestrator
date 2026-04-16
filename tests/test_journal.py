"""Tests for human-readable session journal generation."""
from ralph.core.task_graph import Task, TaskGraph, TaskResult, TaskStatus
from ralph.memory.journal import JournalWriter


class TestJournalWriter:
    def test_write_creates_markdown_summary(self, tmp_path):
        initial = TaskGraph(session_id="s1", goal="Add dark mode")
        initial = initial.with_task(
            Task(id="t1", description="Write tests", agent="claude_code")
        )

        final = initial.with_task(
            Task(
                id="t1",
                description="Write tests",
                agent="claude_code",
                status=TaskStatus.DONE,
                result=TaskResult(success=True, output="tests added", exit_code=0),
            )
        ).with_task(
            Task(
                id="t2",
                description="Implement dark mode",
                agent="claude_code",
                task_type="implementation",
                status=TaskStatus.ESCALATED,
                result=TaskResult(success=False, error="Merge conflict", exit_code=1),
            )
        )

        writer = JournalWriter(tmp_path / ".ralph")
        path = writer.write(initial_graph=initial, final_graph=final, trigger="session_end")

        assert path.exists()
        content = path.read_text()
        assert "# Ralph Session Journal" in content
        assert "Outcome: `attention_required`" in content
        assert "### Completed" in content
        assert "### Escalated" in content
        assert "Merge conflict" in content
        assert "## Current Task Graph" in content

    def test_write_reports_no_task_changes(self, tmp_path):
        graph = TaskGraph(session_id="s1", goal="No-op")
        writer = JournalWriter(tmp_path / ".ralph")

        path = writer.write(initial_graph=graph, final_graph=graph, trigger="session_end")

        assert "No task changes were recorded in this run." in path.read_text()
