from pathlib import Path

import pytest

from resume_builder.web_agent_state import WebAgentState


def test_threads_and_turns_survive_reopening(tmp_path: Path) -> None:
    path = tmp_path / "agent.sqlite"
    state = WebAgentState(path)
    thread = state.create_thread("resumes/baselines/support.md")
    assert state.begin_turn(thread["id"], "run-1", "Help with the summary")
    state.finish_turn(thread["id"], "run-1", "Here are some alternatives.")
    restored = WebAgentState(path).thread(thread["id"])
    assert restored["resume_id"] == thread["resume_id"]
    assert [m["role"] for m in restored["messages"]] == ["user", "assistant"]
    assert not state.begin_turn(thread["id"], "run-1", "Help with the summary")
    with pytest.raises(ValueError, match="different"):
        state.begin_turn(thread["id"], "run-1", "Different request")


def test_only_one_turn_and_proposal_claim_can_run(tmp_path: Path) -> None:
    state = WebAgentState(tmp_path / "agent.sqlite")
    thread = state.create_thread(None)["id"]
    state.begin_turn(thread, "one", "Hello")
    with pytest.raises(ValueError, match="running"):
        state.begin_turn(thread, "two", "Hello")
    proposal = state.propose(thread, {"before": "Old", "after": "New"})
    assert state.claim_proposal(thread, proposal["id"])
    assert not state.claim_proposal(thread, proposal["id"])
    second = state.propose(thread, {"before": "Other", "after": "Replacement"})
    with pytest.raises(ValueError, match="still being reviewed"):
        state.claim_proposal(thread, second["id"])
    state.finish_proposal(thread, proposal["id"], "applied", "Saved")
    assert not state.claim_proposal(thread, proposal["id"])


def test_interruptions_and_thread_isolation(tmp_path: Path) -> None:
    state = WebAgentState(tmp_path / "agent.sqlite")
    a, b = state.create_thread(None)["id"], state.create_thread(None)["id"]
    state.begin_turn(a, "one", "Hello")
    proposal = state.propose(a, {"before": "Old", "after": "New"})
    with pytest.raises(LookupError):
        state.claim_proposal(b, proposal["id"])
    state.recover_interrupted()
    assert state.thread(a)["runs"][0]["status"] == "interrupted"
    assert state.thread(a)["proposals"][0]["status"] == "pending"
    state.delete_thread(a)
    with pytest.raises(LookupError):
        state.thread(a)
    assert len(state.list_threads()) == 1
