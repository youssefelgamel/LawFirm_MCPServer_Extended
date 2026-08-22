from __future__ import annotations
import os
import sys
from langgraph.types import Command
from state_graph.checkpointer import DBCheckpointSaver
from state_graph.conflict_clearance import graph as conflict_graph
import requests

THREAD_ID = "conflict-test-thread"

class FakeConflictResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "results": ["No conflicting party found."]
        }


def record_node(node_name: str, log_file: str) -> None:
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(node_name + "\n")


def install_test_hooks(log_file: str, mode: str) -> None:
    original_intake = conflict_graph.intake_node
    original_conflict = conflict_graph.decompose_conflict_check_node
    original_search = conflict_graph.search_node
    original_evaluate = conflict_graph.evaluate_node
    original_retrieve_policy = conflict_graph.retrieve_policy_node  
    original_draft = conflict_graph.draft_memo_node
    original_signoff = conflict_graph.partner_signoff_node

    def intake_hook(state):
        record_node("intake", log_file)
        return original_intake(state)

    def conflict_hook(state):
        record_node("decompose_conflict_check", log_file)
        return original_conflict(state)
    
    def search_hook(state, config):
        record_node("search", log_file)
        return original_search(state, config)

    def evaluate_hook(state):
        record_node("evaluate", log_file)
        return original_evaluate(state)

    def retrieve_policy_hook(state):                              
        record_node("retrieve_policy", log_file)
        return original_retrieve_policy(state)

    def draft_hook(state):
        record_node("draft_memo", log_file)
        return original_draft(state)


    def signoff_hook(state, config):
        record_node("awaiting_partner_signoff", log_file)
        if mode == "crash":
            os._exit(42)
        if mode == "recover":
            return {"partner_approved": True, "status": "cleared"}
        return original_signoff(state, config)

    conflict_graph.intake_node = intake_hook
    conflict_graph.decompose_conflict_check_node = conflict_hook
    conflict_graph.search_node = search_hook
    conflict_graph.evaluate_node = evaluate_hook
    conflict_graph.retrieve_policy_node = retrieve_policy_hook
    conflict_graph.draft_memo_node = draft_hook
    conflict_graph.partner_signoff_node = signoff_hook


def fake_conflict_search(*args, **kwargs):
    return FakeConflictResponse()



def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "Usage: conflict_worker.py <db_path> <log_file> <mode>"
        )

    db_path = sys.argv[1]
    log_file = sys.argv[2]
    mode = sys.argv[3]

    if mode in {"normal", "crash"}:
        requests.post = fake_conflict_search

    valid_modes = {"crash", "recover", "normal", "start", "resume"}
    if mode not in valid_modes:
        raise ValueError(f"Unknown mode: {mode}")

    install_test_hooks(log_file, mode)

    checkpointer = DBCheckpointSaver(db_path)
    graph = conflict_graph.build_graph(checkpointer)

    config = {
        "configurable": {
            "thread_id": THREAD_ID,
            "db_path": db_path,
        }
    }

    if mode in {"start", "normal"}:
        result = graph.invoke(
            {
                "case_id": "case-test",
                "status": "intake",
                "conflict_found": False,
                "partner_approved": False,
            },
            config,
            durability="sync",
        )
        print(result)
        if isinstance(result, dict):
            print("CHECKLIST:", result.get("check_list"))

    elif mode == "crash":
        graph.invoke(
            {
                "case_id": "case-test",
                "status": "intake",
                "conflict_found": False,
                "partner_approved": False,
            },
            config,
            durability="sync",
        )

    elif mode == "resume":
        result = graph.invoke(
            Command(resume=True),
            config,
            durability="sync",
        )
        print(result)

    elif mode == "recover":
        result = graph.invoke(
            None,
            config,
            durability="sync",
        )
        print(result)


if __name__ == "__main__":
    main()