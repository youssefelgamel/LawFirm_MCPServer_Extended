from __future__ import annotations
import uuid
from mcp_server.database import get_connection


def open_ticket(db_path: str, case_id: str, thread_id: str,
                 checkpoint_id: str | None, error_message: str) -> str:
    """Open a ticket for a conflict-search failure. Returns the new ticket_id."""
    ticket_id = str(uuid.uuid4())
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tickets (ticket_id, case_id, thread_id, checkpoint_id, status, error_message)
            VALUES (?, ?, ?, ?, 'open', ?)
            """,
            (ticket_id, case_id, thread_id, checkpoint_id, error_message),
        )
        conn.commit()
    return ticket_id


def get_ticket(db_path: str, ticket_id: str) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT ticket_id, case_id, thread_id, checkpoint_id, status, error_message
            FROM tickets WHERE ticket_id = ?
            """,
            (ticket_id,),
        ).fetchone()
    if row is None:
        return None
    columns = ["ticket_id", "case_id", "thread_id", "checkpoint_id", "status", "error_message"]
    return dict(zip(columns, row))


def mark_ticket_resolved(db_path: str, ticket_id: str, resolved_by: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE tickets
            SET status = 'resolved', resolved_by = ?, resolved_at = datetime('now')
            WHERE ticket_id = ?
            """,
            (resolved_by, ticket_id),
        )
        conn.commit()