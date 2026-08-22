from __future__ import annotations
from state_graph.checkpointer import DBCheckpointSaver
from state_graph.conflict_clearance.graph import build_graph
from state_graph.conflict_clearance.tickets import get_ticket, mark_ticket_resolved


def resume_from_ticket(db_path: str, ticket_id: str, resolved_by: str) -> dict:
    """
    Call this from wherever your platform resolves a ticket (button, admin
    endpoint, CLI -- doesn't matter). Marks the ticket resolved, then resumes
    the LangGraph run with None input on the same thread_id. Since `search`
    is the node that never completed, this re-enters `search` -- NOT intake.
    """
    ticket = get_ticket(db_path, ticket_id)
    if ticket is None:
        raise ValueError(f"no ticket {ticket_id}")
    if ticket["status"] != "open":
        raise ValueError(f"ticket {ticket_id} is already {ticket['status']}")

    mark_ticket_resolved(db_path, ticket_id, resolved_by)

    checkpointer = DBCheckpointSaver(db_path)
    graph = build_graph(checkpointer)
    config = {"configurable": {"thread_id": ticket["thread_id"], "db_path": db_path}}
    return graph.invoke(None, config, durability="sync")