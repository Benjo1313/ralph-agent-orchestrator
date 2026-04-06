"""Task graph models for Ralph's orchestration loop."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, computed_field


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.SKIPPED)


class TaskResult(BaseModel):
    success: bool
    output: str | None = None
    error: str | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Task(BaseModel, frozen=True):
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    agent: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    result: TaskResult | None = None
    attempt: int = 0

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal


class TaskGraph(BaseModel, frozen=True):
    session_id: str
    goal: str
    tasks: dict[str, Task] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def with_task(self, task: Task) -> "TaskGraph":
        """Return a new TaskGraph with the task added or updated."""
        updated_tasks = {**self.tasks, task.id: task}
        return self.model_copy(
            update={"tasks": updated_tasks, "updated_at": datetime.now(timezone.utc)}
        )

    def ready_tasks(self) -> list[Task]:
        """Return tasks whose dependencies are all terminal and that are not themselves terminal."""
        ready = []
        for task in self.tasks.values():
            if task.is_terminal:
                continue
            deps_met = all(
                self.tasks.get(dep_id, Task(id=dep_id, description="")).is_terminal
                for dep_id in task.dependencies
            )
            if deps_met:
                ready.append(task)
        return ready

    @property
    def is_complete(self) -> bool:
        return all(t.is_terminal for t in self.tasks.values())

    @property
    def has_failures(self) -> bool:
        return any(t.status == TaskStatus.FAILED for t in self.tasks.values())
