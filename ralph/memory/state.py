"""StateManager: persist and resume TaskGraph via state.json."""
import json
from pathlib import Path

from pydantic import ValidationError

from ralph.core.task_graph import TaskGraph


class StateError(Exception):
    pass


class StateManager:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def has_saved_state(self) -> bool:
        return self.state_file.exists()

    def save(self, graph: TaskGraph) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(graph.model_dump_json(indent=2))

    def load(self) -> TaskGraph:
        if not self.has_saved_state:
            raise StateError("No saved state found.")
        try:
            raw = json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise StateError(f"State file is corrupt: {e}") from e
        try:
            return TaskGraph.model_validate(raw)
        except (ValidationError, TypeError) as e:
            raise StateError(f"State file has invalid schema: {e}") from e

    def clear(self) -> None:
        if self.state_file.exists():
            self.state_file.unlink()
