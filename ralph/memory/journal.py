"""Human-readable journal entries written separately from machine state."""
from datetime import UTC, datetime
from pathlib import Path

from ralph.core.task_graph import Task, TaskGraph, TaskStatus


class JournalWriter:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    @property
    def journal_dir(self) -> Path:
        return self.state_dir / "journal"

    def write(
        self,
        initial_graph: TaskGraph,
        final_graph: TaskGraph,
        trigger: str = "session_end",
    ) -> Path:
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC)
        slug = trigger.replace(" ", "-")
        filename = (
            f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{final_graph.session_id}-{slug}.md"
        )
        path = self.journal_dir / filename
        path.write_text(self._render_entry(initial_graph, final_graph, timestamp, trigger))
        return path

    def _render_entry(
        self,
        initial_graph: TaskGraph,
        final_graph: TaskGraph,
        timestamp: datetime,
        trigger: str,
    ) -> str:
        progress = self._progress_line(final_graph)
        outcome = self._outcome(final_graph)
        lines = [
            "# Ralph Session Journal",
            "",
            f"- Session: `{final_graph.session_id}`",
            f"- Goal: {final_graph.goal}",
            f"- Trigger: `{trigger}`",
            f"- Written: `{timestamp.isoformat()}`",
            f"- Outcome: `{outcome}`",
            f"- Progress: {progress}",
            "",
            "## Activity This Run",
        ]

        lines.extend(self._activity_lines(initial_graph, final_graph))
        lines.extend(["", "## Current Task Graph"])
        lines.extend(self._task_lines(final_graph))
        lines.append("")
        return "\n".join(lines)

    def _activity_lines(self, initial_graph: TaskGraph, final_graph: TaskGraph) -> list[str]:
        initial_tasks = initial_graph.tasks
        final_tasks = final_graph.tasks

        completed = []
        failed = []
        escalated = []
        skipped = []
        retried = []
        added = []

        for task in final_tasks.values():
            before = initial_tasks.get(task.id)
            before_status = before.status if before is not None else None
            before_attempt = before.attempt if before is not None else 0

            if before is None:
                added.append(self._task_summary(task))

            if task.attempt > before_attempt:
                retried.append(
                    f"- Retry count increased for `{task.id}` to {task.attempt}: {task.description}"
                )

            if task.status == TaskStatus.DONE and before_status != TaskStatus.DONE:
                completed.append(self._task_summary(task))
            elif task.status == TaskStatus.FAILED and before_status != TaskStatus.FAILED:
                failed.append(self._task_summary(task, include_error=True))
            elif task.status == TaskStatus.ESCALATED and before_status != TaskStatus.ESCALATED:
                escalated.append(self._task_summary(task, include_error=True))
            elif task.status == TaskStatus.SKIPPED and before_status != TaskStatus.SKIPPED:
                skipped.append(self._task_summary(task))

        lines: list[str] = []
        if added:
            lines.extend(["### Planned", *added])
        if completed:
            lines.extend(["### Completed", *completed])
        if retried:
            lines.extend(["### Retried", *retried])
        if failed:
            lines.extend(["### Failed", *failed])
        if escalated:
            lines.extend(["### Escalated", *escalated])
        if skipped:
            lines.extend(["### Skipped", *skipped])
        if not lines:
            return ["No task changes were recorded in this run."]
        return lines

    def _task_lines(self, graph: TaskGraph) -> list[str]:
        if not graph.tasks:
            return ["No tasks are currently tracked."]
        return [self._task_summary(task, include_error=True) for task in graph.tasks.values()]

    def _task_summary(self, task: Task, include_error: bool = False) -> str:
        agent = task.agent or "unrouted"
        summary = f"- `{task.status}` `{task.id}` via `{agent}`"
        if task.attempt:
            summary += f" attempts={task.attempt}"
        summary += f": {task.description}"
        if include_error and task.result and task.result.error:
            summary += f" | error: {task.result.error}"
        return summary

    def _outcome(self, graph: TaskGraph) -> str:
        if any(
            task.status in (TaskStatus.FAILED, TaskStatus.ESCALATED)
            for task in graph.tasks.values()
        ):
            return "attention_required"
        if all(task.status == TaskStatus.SKIPPED for task in graph.tasks.values()) and graph.tasks:
            return "skipped"
        if graph.is_complete:
            return "completed"
        return "in_progress"

    def _progress_line(self, graph: TaskGraph) -> str:
        total = len(graph.tasks)
        counts = {
            status.value: sum(1 for task in graph.tasks.values() if task.status == status)
            for status in TaskStatus
        }
        terminal = sum(counts[status.value] for status in TaskStatus if status.is_terminal)
        return (
            f"{terminal}/{total} terminal | "
            f"done={counts['done']}, failed={counts['failed']}, "
            f"escalated={counts['escalated']}, skipped={counts['skipped']}, "
            f"pending={counts['pending']}, in_progress={counts['in_progress']}"
        )
