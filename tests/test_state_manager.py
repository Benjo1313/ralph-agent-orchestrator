"""Tests for StateManager (load/save state.json, resume detection)."""
import json

import pytest

from ralph.core.task_graph import Task, TaskGraph, TaskStatus
from ralph.memory.state import StateError, StateManager


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / ".ralph"


@pytest.fixture
def manager(state_dir):
    return StateManager(state_dir=state_dir)


@pytest.fixture
def sample_graph():
    g = TaskGraph(session_id="session-abc", goal="Add dark mode toggle")
    t1 = Task(id="t1", description="Write failing test", status=TaskStatus.DONE)
    t2 = Task(
        id="t2",
        description="Implement feature",
        retry_guidance="Fix the failing assertions before retrying",
    )
    return g.with_task(t1).with_task(t2)


class TestStateManagerInit:
    def test_creates_state_dir_on_save(self, manager, sample_graph):
        assert not manager.state_dir.exists()
        manager.save(sample_graph)
        assert manager.state_dir.exists()

    def test_state_file_path(self, manager):
        assert manager.state_file == manager.state_dir / "state.json"


class TestStateManagerSave:
    def test_save_creates_valid_json(self, manager, sample_graph):
        manager.save(sample_graph)
        raw = json.loads(manager.state_file.read_text())
        assert raw["session_id"] == "session-abc"
        assert raw["goal"] == "Add dark mode toggle"
        assert "t1" in raw["tasks"]
        assert "t2" in raw["tasks"]

    def test_save_is_idempotent(self, manager, sample_graph):
        manager.save(sample_graph)
        manager.save(sample_graph)
        raw = json.loads(manager.state_file.read_text())
        assert raw["session_id"] == "session-abc"

    def test_save_overwrites_previous(self, manager, sample_graph):
        manager.save(sample_graph)
        updated = sample_graph.model_copy(update={"goal": "Updated goal"})
        manager.save(updated)
        raw = json.loads(manager.state_file.read_text())
        assert raw["goal"] == "Updated goal"


class TestStateManagerLoad:
    def test_load_round_trips(self, manager, sample_graph):
        manager.save(sample_graph)
        loaded = manager.load()
        assert loaded.session_id == sample_graph.session_id
        assert loaded.goal == sample_graph.goal
        assert loaded.tasks["t1"].status == TaskStatus.DONE
        assert loaded.tasks["t2"].status == TaskStatus.PENDING
        assert loaded.tasks["t2"].retry_guidance == "Fix the failing assertions before retrying"

    def test_load_raises_when_no_state(self, manager):
        with pytest.raises(StateError, match="No saved state"):
            manager.load()

    def test_load_raises_on_corrupt_json(self, manager):
        manager.state_dir.mkdir(parents=True)
        manager.state_file.write_text("this is not json {{{")
        with pytest.raises(StateError, match="corrupt"):
            manager.load()

    def test_load_raises_on_invalid_schema(self, manager):
        manager.state_dir.mkdir(parents=True)
        manager.state_file.write_text('{"not_a_valid_graph": true}')
        with pytest.raises(StateError, match="invalid"):
            manager.load()


class TestStateManagerResume:
    def test_has_saved_state_false_when_no_dir(self, manager):
        assert not manager.has_saved_state

    def test_has_saved_state_false_when_no_file(self, manager):
        manager.state_dir.mkdir(parents=True)
        assert not manager.has_saved_state

    def test_has_saved_state_true_after_save(self, manager, sample_graph):
        manager.save(sample_graph)
        assert manager.has_saved_state

    def test_clear_removes_state_file(self, manager, sample_graph):
        manager.save(sample_graph)
        manager.clear()
        assert not manager.has_saved_state

    def test_clear_is_noop_when_no_state(self, manager):
        manager.clear()  # should not raise
        assert not manager.has_saved_state
