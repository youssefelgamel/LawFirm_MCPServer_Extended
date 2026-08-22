# $env:PYTHONPATH="."
# pytest tests/test_checkpointer.py tests/test_conflict_clearance.py -v

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from state_graph.checkpointer import DBCheckpointSaver
from state_graph.conflict_clearance import graph as conflict_graph
from state_graph.conflict_clearance.resume_ticket import resume_from_ticket



ROOT_DIR = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT_DIR / "db" / "schema.sql"
WORKER_FILE = ROOT_DIR / "tests" / "conflict_worker.py"


def create_test_database(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    conn.executescript(
        SCHEMA_FILE.read_text(encoding="utf-8")
    )

    # Seed minimal parent rows so FK-constrained inserts made by the
    # graph (e.g. hitl_tasks.case_id -> case.case_id) succeed.
    conn.execute(
        """
        INSERT INTO party (party_id, full_name, party_type)
        VALUES ('party-test', 'Test Client', 'client')
        """
    )
    conn.execute(
        """
        INSERT INTO case_type_policy (
            policy_id, case_type, min_seniority_required,
            required_documents, auto_reject_if_conflict
        )
        VALUES ('policy-test', 'civil', 1, '[]', 0)
        """
    )
    conn.execute(
        """
        INSERT INTO staff (staff_id, full_name, role, email, active)
        VALUES ('staff-test', 'Test Partner', 'partner', 'partner@test.local', 1)
        """
    )
    conn.execute(
        """
        INSERT INTO "case" (
            case_id, client_party_id, policy_id, description
        )
        VALUES ('case-test', 'party-test', 'policy-test', 'Test case for conflict clearance')
        """
    )

    conn.commit()
    conn.close()


def run_worker(db_path: Path, log_file: Path, mode: str,) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT_DIR)

    return subprocess.run([sys.executable, str(WORKER_FILE), str(db_path), str(log_file), mode,],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        env=env,
    )


def test_conflict_clearance_recovers_after_process_kill(tmp_path):
    db_path = tmp_path / "case_intake_test.db"
    log_file = tmp_path / "nodes.log"

    create_test_database(db_path)

    # Process 1: run until running_conflict_check completes,
    # then kill the process at the next node.
    crashed = run_worker(
        db_path,
        log_file,
        "crash",
    )

    assert crashed.returncode == 42

    first_run_nodes = log_file.read_text(encoding="utf-8").splitlines()

    assert first_run_nodes == [
        "intake",
        "decompose_conflict_check",
        "search",
        "evaluate",
        "retrieve_policy",
        "draft_memo",
        "awaiting_partner_signoff",
    ]

    # Confirm checkpoints exist directly in our database.
    conn = sqlite3.connect(db_path)

    checkpoint_count_before = conn.execute(
        """
        SELECT COUNT(*)
        FROM graph_checkpoint
        WHERE thread_id = ?
        """,
        ("conflict-test-thread",),
    ).fetchone()[0]

    conn.close()

    # We should have:
    # input checkpoint + intake checkpoint + conflict-check checkpoint.
    assert checkpoint_count_before >= 3

    # Process 2: resume from the latest saved checkpoint.
    recovered = run_worker(
        db_path,
        log_file,
        "recover",
    )

    assert recovered.returncode == 0
    assert "cleared" in recovered.stdout

    all_nodes = log_file.read_text(
        encoding="utf-8"
    ).splitlines()

    # intake and running_conflict_check were completed before the crash
    # and therefore must not execute again.
    assert all_nodes.count("intake") == 1
    assert all_nodes.count("decompose_conflict_check") == 1
    assert all_nodes.count("search") == 1
    assert all_nodes.count("evaluate") == 1
    assert all_nodes.count("retrieve_policy") == 1
    assert all_nodes.count("draft_memo") == 1
    assert all_nodes.count("awaiting_partner_signoff") == 2

    # Recovery should have produced additional checkpoints.
    conn = sqlite3.connect(db_path)

    checkpoint_count_after = conn.execute(
        """
        SELECT COUNT(*)
        FROM graph_checkpoint
        WHERE thread_id = ?
        """,
        ("conflict-test-thread",),
    ).fetchone()[0]

    conn.close()

    assert checkpoint_count_after > checkpoint_count_before

def test_conflict_check_generates_ordered_checklist(tmp_path):
    db_path = tmp_path / "case_intake_test.db"
    log_file = tmp_path / "nodes.log"

    create_test_database(db_path)

    result = run_worker(
        db_path,
        log_file,
        "normal",
    )

    assert result.returncode == 0

    assert (
        "CHECKLIST: ['search', 'evaluate', 'draft_memo']"
        in result.stdout
    )

    nodes = log_file.read_text(encoding="utf-8").splitlines()

    assert nodes[:7] == [
        "intake",
        "decompose_conflict_check",
        "search",
        "evaluate",
        "retrieve_policy",
        "draft_memo",
        "awaiting_partner_signoff",
    ]

# Add these imports near the top of test_conflict_clearance.py:
#
# import requests
# from unittest.mock import Mock
# from state_graph.conflict_clearance.graph import ConflictSearchError
# from state_graph.resume_ticket import resume_from_ticket

THREAD_ID_TICKET = "ticket-test-thread"


def test_conflict_search_failure_opens_ticket_and_resumes(tmp_path, monkeypatch):
    db_path = tmp_path / "case_intake_test.db"
    create_test_database(db_path)

    monkeypatch.setattr(
        requests, "post",
        Mock(side_effect=requests.exceptions.Timeout("conflict service timed out")),
    )

    checkpointer = DBCheckpointSaver(str(db_path))
    graph = conflict_graph.build_graph(checkpointer)
    config = {"configurable": {"thread_id": THREAD_ID_TICKET, "db_path": str(db_path)}}

    with pytest.raises(conflict_graph.ConflictSearchError):
        graph.invoke(
            {"case_id": "case-test", "status": "intake",
             "conflict_found": False, "partner_approved": False},
            config,
            durability="sync",
        )

    # 2) A ticket exists, is open, and carries a checkpoint_id.
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT ticket_id, status, checkpoint_id FROM tickets WHERE thread_id = ?",
        (THREAD_ID_TICKET,),
    ).fetchone()
    conn.close()

    assert row is not None
    ticket_id, status, checkpoint_id = row
    assert status == "open"
    assert checkpoint_id is not None

    # 3) Make the service succeed now, and resolve the ticket.
    ok_response = Mock()
    ok_response.raise_for_status = Mock()
    ok_response.json = Mock(return_value={"results": ["No conflicting party found."]})
    monkeypatch.setattr(requests, "post", Mock(return_value=ok_response))

    result = resume_from_ticket(str(db_path), ticket_id, resolved_by="staff-test")

    # 4) It reached a final decision (search re-ran, not intake) and the
    #    ticket is now resolved.
    assert result["status"] in {"cleared", "rejected"}

    conn = sqlite3.connect(db_path)
    resolved_status = conn.execute(
        "SELECT status FROM tickets WHERE ticket_id = ?", (ticket_id,)
    ).fetchone()[0]
    conn.close()
    assert resolved_status == "resolved"