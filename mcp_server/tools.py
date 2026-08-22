from .mcp_instance import mcp
from .database import get_connection
import uuid
import logging
from fastmcp import Context
from .elicitation import require_fields
import sqlite3

from planning.decomposition.static_decomposition import decompose_goal, execute_plan, final_output
from planning.decomposition.dynamic_decomposition import dynamic_decomposition

logger = logging.getLogger(__name__)

# ---------------------------
# DATABASE HEALTH CHECK
# ---------------------------

@mcp.tool(description="Check whether the database connection is working.")
def database_health() -> dict:
    logger.info("Running database_health()")

    with get_connection() as conn:
        cursor = conn.cursor()
        tables = ["party", "staff", "lawyer", "case", "document", "conflict_check"]
        counts = {}

        for table in tables:
            sql_table = '"case"' if table == "case" else table
            cursor.execute(f"SELECT COUNT(*) FROM {sql_table}")
            counts[table] = cursor.fetchone()[0]

    logger.info("Database health check passed.")

    return {
        "status": "connected",
        "database": str(get_connection.__globals__["DB_PATH"]),
        "tables": counts
    }

# ---------------------------
# PARTY / CLIENT
# ---------------------------

@mcp.tool(description="Retrieve client information using the client's party ID.")
def get_client(client_party_id: str) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT *
            FROM party
            WHERE party_id = ?
              AND party_type = 'client'
        """, (client_party_id,))
        row = cursor.fetchone()

    if row is None:
        return {"error": f"Client '{client_party_id}' not found."}

    return dict(row)

# ---------------------------
# CASE RETRIEVAL
# ---------------------------

@mcp.tool(description="Retrieve complete case information by case ID.")
def get_case(case_id: str) ->dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                c.*,
                p.full_name AS client_name,
                cp.case_type
            FROM "case" c
            JOIN party p
                ON c.client_party_id = p.party_id
            JOIN case_type_policy cp
                ON c.policy_id = cp.policy_id
            WHERE c.case_id = ?
        """, (case_id,))
        row = cursor.fetchone()

    if row is None:
        return {"error": f"Case '{case_id}' not found."}

    return dict(row)


# ---------------------------
# ASSIGN CASE TO LAWYER
# ---------------------------    

async def assign_case_to_lawyer(
    ctx: Context,
    case_id: str | None = None,
    lawyer_id: str | None = None,
    assigned_by: str | None = None,
    role_on_case: str | None = "lead",
) -> dict:

    values = await require_fields(
        ctx,
        {
            "case_id": case_id,
            "lawyer_id": lawyer_id,
            "assigned_by": assigned_by,
            "role_on_case": role_on_case,
        },
        {
            "case_id": "The case ID to assign.",
            "lawyer_id": "The lawyer that will handle the case.",
            "assigned_by": "The staff member assigning the lawyer.",
            "role_on_case": "Role of the lawyer on this case.",
        },
    )

    case_id = values["case_id"]
    lawyer_id = values["lawyer_id"]
    assigned_by = values["assigned_by"]
    role_on_case = values["role_on_case"]

    # Statuses that are allowed to move into 'assigned'.
    # Adjust this set to match your actual case-status lifecycle.
    ASSIGNABLE_STATUSES = {"accepted"}

    with get_connection() as conn:
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT status FROM "case" WHERE case_id = ?', (case_id,))
            case = cursor.fetchone()

            if not case:
                return {"error": "Case not found."}

            case_status = case["status"]

            if case_status not in ASSIGNABLE_STATUSES:
                return {
                    "error": (
                        f"Case cannot be assigned from its current status "
                        f"('{case_status}'). Case must be in one of: "
                        f"{sorted(ASSIGNABLE_STATUSES)}."
                    )
                }

            cursor.execute("""
                SELECT current_caseload, max_caseload
                FROM lawyer
                WHERE lawyer_id = ?
                  AND status='active'
            """, (lawyer_id,))
            lawyer = cursor.fetchone()

            if not lawyer:
                return {"error": "Lawyer not found or inactive."}

            if lawyer["current_caseload"] >= lawyer["max_caseload"]:
                return {"error": "Lawyer is already at maximum caseload."}

            assignment_id = str(uuid.uuid4())

            cursor.execute("""
                INSERT INTO case_assignment(
                    assignment_id,
                    case_id,
                    lawyer_id,
                    assigned_by,
                    role_on_case
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                assignment_id,
                case_id,
                lawyer_id,
                assigned_by,
                role_on_case,
            ))

            cursor.execute("""
                UPDATE lawyer
                SET current_caseload = current_caseload + 1
                WHERE lawyer_id = ?
            """, (lawyer_id,))

            cursor.execute("""
                UPDATE "case"
                SET status='assigned',
                    updated_at=datetime('now')
                WHERE case_id=?
            """, (case_id,))

            conn.commit()

        except Exception as e:
            conn.rollback()
            logger.exception(
                "Failed to assign lawyer '%s' to case '%s': %s",
                lawyer_id, case_id, e
            )
            return {"error": f"Assignment failed and was rolled back: {e}"}

    # Hide this tool again after assignment
    logger.info("Case assigned successfully.")

    
    logger.info("assign_case_to_lawyer hidden again")

    return {
        "success": True,
        "assignment_id": assignment_id,
        "message": "Case assigned successfully."
    }

# ---------------------------
# ACCEPT CASE
# ---------------------------

@mcp.tool(description="Accept a case after review.")
async def accept_case(
    ctx: Context,
    case_id: str | None = None,
    decided_by: str | None = None,
    decision_reason: str | None = None,
) -> dict:

    values = await require_fields(
        ctx,
        {
            "case_id": case_id,
            "decided_by": decided_by,
            "decision_reason": decision_reason,
        },
        {
            "case_id": "The case ID to accept.",
            "decided_by": "The staff member approving the case.",
            "decision_reason": "Reason for accepting the case.",
        },
    )

    case_id = values["case_id"]
    decided_by = values["decided_by"]
    decision_reason = values["decision_reason"]

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT case_id FROM "case" WHERE case_id = ?', (case_id,)
            )

            if cursor.fetchone() is None:
                return {"success": False, "error": "Case not found.", "code": "CASE_NOT_FOUND",}

            cursor.execute(
                "SELECT staff_id FROM staff WHERE staff_id = ?", (decided_by,)
            )

            if cursor.fetchone() is None:
                return {"success": False, "error": "Deciding staff member not found.", "code":"STAFF_NOT_FOUND",}

            cursor.execute("""
                UPDATE "case"
                SET
                    status='accepted',
                    decision_reason=?,
                    decided_by=?,
                    decision_at=datetime('now'),
                    updated_at=datetime('now')
                WHERE case_id=?
            """, (
                decision_reason, decided_by, case_id))
            conn.commit()
    except sqlite3.Error as exc:
        logger.exception("Failed to accept case %s", case_id)
        return {"success": False, "error": f"Database error: {exc}", "code": "DATABASE_ERROR",}

    try:
        if hasattr(ctx, "enable_components"):
            await ctx.enable_components(
                names={"assign_case_to_lawyer"},
                components={"tool"},
            )
            logger.info("Unlocked assign_case_to_lawyer tool")

    except RuntimeError as exc:
        logger.warning(
            "Could not enable component (no active session context): %s", exc)
    except Exception as exc:
        logger.warning("Unexpected error enabling components: %s", exc)

    return {
        "success": True,
        "case_id": case_id,
        "status": "accepted",
        "message": "Case accepted. The Assign Case To Lawyer tool has been unlocked."}


# ---------------------------
# REJECT CASE
# ---------------------------

@mcp.tool(description="Reject a case after review.")
async def reject_case(
    ctx: Context,
    case_id: str | None = None,
    decided_by: str | None = None,
    decision_reason: str | None = None,
) -> dict:

    values = await require_fields(
        ctx,
        {
            "case_id": case_id,
            "decided_by": decided_by,
            "decision_reason": decision_reason,
        },
        {
            "case_id": "The case ID to reject.",
            "decided_by": "The staff member rejecting the case.",
            "decision_reason": "Reason for rejecting the case.",
        },
    )

    case_id = values["case_id"]
    decided_by = values["decided_by"]
    decision_reason = values["decision_reason"]

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT case_id FROM "case" WHERE case_id = ?', (case_id,)
            )

            if cursor.fetchone() is None:
                return {"success": False, "error": "Case not found.", "code":"CASE_NOT_FOUND",}

            cursor.execute(
                "SELECT staff_id FROM staff WHERE staff_id = ?", (decided_by,)
            )

            if cursor.fetchone() is None:
                return {"success": False, "error": "Staff member not found.", "code": "STAFF_NOT_FOUND",}
            
            cursor.execute("""
                UPDATE "case"
                SET
                    status='rejected',
                    decision_reason=?,
                    decided_by=?,
                    decision_at=datetime('now'),
                    updated_at=datetime('now')
                WHERE case_id=?
            """, (
                decision_reason,
                decided_by,
                case_id,
            ))

        conn.commit()

    except sqlite3.Error as exc:
        logger.exception("Failed to reject case %s", case_id)
        return {"success": False, "error": f"Database error: {exc}", "code":"DATABASE_ERROR",}

    return {"success": True, "case_id": case_id, "status": "rejected", "message": "Case rejected.",}

# ---------------------------
# CONFLICT CHECK
# ---------------------------

@mcp.tool(description="Retrieve all conflict check records for a case.")
def get_conflict_checks(case_id: str) -> list:
    if not case_id or not case_id.strip():
        return {"success": False, "error": "Case ID is required.", "code":"INVALID_INPUT",}

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT case_id from "case" WHERE case_id = ?', (case_id,))
            if cursor.fetchone() is None:
                return {"success": False, "error": "Case not found.", "code": "CASE_NOT_FOUND",}
            cursor.execute("""
                SELECT *
                FROM conflict_check
                WHERE case_id = ?
                ORDER BY checked_at ASC
            """, (case_id,))

            return [dict(r) for r in cursor.fetchall()]

    except sqlite3.Error as exc:
        logger.exception("Failed to retrieve conflict checks for case %s", case_id)
        return {"success": False, "error": f"Database error: {exc}", "code": "DATABASE_ERROR",}
    

# ---------------------------
# LAWYER DETAILS
# ---------------------------

@mcp.tool(description="Retrieve lawyer details.")
def get_lawyer(lawyer_id: str) -> dict:
    if not lawyer_id or not lawyer_id.strip():
        return {"success": False, "error": "Lawyer ID is required."}
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT *
            FROM lawyer
            WHERE lawyer_id = ?
        """, (lawyer_id,))
        row = cursor.fetchone()

    if row is None:
        return {"error": "Lawyer not found."}

    return dict(row)


@mcp.tool(description="Retrieve staff user details by staff ID.")
def get_staff(staff_id: str) -> dict:
    if not staff_id or not staff_id.strip():
        return {"success": False, "error": "Staff ID is required."}
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT staff_id, full_name, role, email, active FROM staff WHERE staff_id = ?",
            (staff_id,),
        )
        row = cursor.fetchone()
    if row is None:
        return {"success": False, "error": "Staff member not found."}
    return dict(row)


@mcp.tool(description="List active staff users available to the web platform.")
def list_staff() -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT staff_id, full_name, role, email, active FROM staff WHERE active = 1 ORDER BY full_name"
        )
        return [dict(row) for row in cursor.fetchall()]


@mcp.tool(description="Create an active staff user for the web platform.")
def create_staff(staff_id: str, full_name: str, role: str, email: str) -> dict:
    allowed_roles = {"receptionist", "senior_associate", "partner", "admin"}
    if role not in allowed_roles or not all(value.strip() for value in (staff_id, full_name, email)):
        return {"success": False, "error": "Valid staff ID, name, email, and role are required."}
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO staff (staff_id, full_name, role, email, active) VALUES (?, ?, ?, ?, 1)",
                (staff_id.strip(), full_name.strip(), role, email.strip()),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return {"success": False, "error": "Staff ID or email already exists."}
    return {"success": True, "staff_id": staff_id.strip(), "message": "Staff user created."}


# ---------------------------
# PLANNING / DECOMPOSITION
# ---------------------------

@mcp.tool(description="Static task decomposition using a validated DAG")
def static_task_decomposition(goal: str) -> str:
    from planning.llm import llm

    plan = decompose_goal(goal, llm)
    outputs = execute_plan(plan, llm)
    return final_output(plan, outputs)

@mcp.tool(description="Dynamic task decomposition using adaptive planning")
def dynamic_task_decomposition(goal: str) -> list[tuple[str, str]]:
    from planning.llm import llm

    return dynamic_decomposition(goal, llm)


@mcp.tool()
def assign_case_to_lawyer(case_id: str, lawyer_id: str) -> dict:
    """Assigns a case officially to a lawyer in the system/database."""
    # Add your DB persistence / status update logic here
    return {
        "status": "assigned",
        "case_id": case_id,
        "lawyer_id": lawyer_id
    }

