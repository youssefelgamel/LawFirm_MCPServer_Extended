import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import json
from mcp_server.server import mcp


# -------------------------------------------------------
# Test Cases
# -------------------------------------------------------

TEST_CASES = [

    # -------------------------
    # Health
    # -------------------------

    {
        "name": "Database Health",
        "tool": "database_health",
        "args": {},
        "expect_error": False,
    },

    # -------------------------
    # Clients
    # -------------------------

    {
        "name": "Get Existing Client",
        "tool": "get_client",
        "args": {
            "client_party_id": "party-001"
        },
        "expect_error": False,
    },

    {
        "name": "Get Missing Client",
        "tool": "get_client",
        "args": {
            "client_party_id": "party-999"
        },
        "expect_error": False,
    },

    # -------------------------
    # Cases
    # -------------------------

    {
        "name": "Get Existing Case",
        "tool": "get_case",
        "args": {
            "case_id": "case-001"
        },
        "expect_error": False,
    },

    {
        "name": "Get Missing Case",
        "tool": "get_case",
        "args": {
            "case_id": "case-999"
        },
        "expect_error": False,
    },

    # -------------------------
    # Lawyers
    # -------------------------

    {
        "name": "Get Existing Lawyer",
        "tool": "get_lawyer",
        "args": {
            "lawyer_id": "lawyer-001"
        },
        "expect_error": False,
    },

    {
        "name": "Get Missing Lawyer",
        "tool": "get_lawyer",
        "args": {
            "lawyer_id": "lawyer-999"
        },
        "expect_error": False,
    },

    # -------------------------
    # Conflict Checks
    # -------------------------

    {
        "name": "Conflict Exists",
        "tool": "get_conflict_checks",
        "args": {
            "case_id": "case-003"
        },
        "expect_error": False,
    },

    {
        "name": "No Conflict",
        "tool": "get_conflict_checks",
        "args": {
            "case_id": "case-001"
        },
        "expect_error": False,
    },

    # -------------------------
    # Assignment
    # -------------------------

    {
        "name": "Assign Lawyer Success",
        "tool": "assign_case_to_lawyer",
        "args": {
            "case_id": "case-002",
            "lawyer_id": "lawyer-001",
            "assigned_by": "staff-002"
        },
        "expect_error": False,
    },

    {
        "name": "Assign Lawyer Full Caseload",
        "tool": "assign_case_to_lawyer",
        "args": {
            "case_id": "case-002",
            "lawyer_id": "lawyer-003",
            "assigned_by": "staff-002"
        },
        "expect_error": False,
    },

    # -------------------------
    # Accept
    # -------------------------

    {
        "name": "Accept Case",
        "tool": "accept_case",
        "args": {
            "case_id": "case-002",
            "decided_by": "staff-002",
            "decision_reason": "Smoke test approval."
        },
        "expect_error": False,
    },

    # -------------------------
    # Reject
    # -------------------------

    {
        "name": "Reject Case",
        "tool": "reject_case",
        "args": {
            "case_id": "case-003",
            "decided_by": "staff-002",
            "decision_reason": "Smoke test rejection."
        },
        "expect_error": False,
    },
]


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def pretty(data):
    print(json.dumps(data, indent=4))


async def test_resources():

    print("\n" + "=" * 70)
    print("RESOURCES")
    print("=" * 70)

    resources = await mcp.list_resources()

    print(f"Found {len(resources)} resources\n")

    passed = 0

    for resource in resources:

        print(f"Reading {resource.uri}")

        try:

            result = await mcp.read_resource(str(resource.uri))

            print("PASS")

            print(result)

            passed += 1

        except Exception as e:

            print("FAIL")

            print(e)

        print("-" * 70)

    return passed, len(resources)


async def test_tools():

    print("\n" + "=" * 70)
    print("TOOLS")
    print("=" * 70)

    passed = 0

    for test in TEST_CASES:

        print(f"\n{test['name']}")
        print(f"Tool: {test['tool']}")

        try:

            result = await mcp.call_tool(
                test["tool"],
                test["args"]
            )

            print("MCP Error :", result.is_error)

            print("Structured Output:")

            pretty(result.structured_content)

            passed += 1

        except Exception as e:

            print("FAILED")

            print(e)

        print("-" * 70)

    return passed, len(TEST_CASES)


async def list_everything():

    print("=" * 70)
    print("REGISTERED TOOLS")
    print("=" * 70)

    tools = await mcp.list_tools()

    for tool in tools:
        print(tool.name)

    print()

    print("=" * 70)
    print("REGISTERED RESOURCES")
    print("=" * 70)

    resources = await mcp.list_resources()

    for resource in resources:
        print(resource.uri)


async def main():

    print("\n")
    print("=" * 70)
    print("LAW FIRM MCP SMOKE TEST")
    print("=" * 70)

    await list_everything()

    resource_passed, resource_total = await test_resources()

    tool_passed, tool_total = await test_tools()

    print("\n")
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"Resources : {resource_passed}/{resource_total}")

    print(f"Tools     : {tool_passed}/{tool_total}")

    total = resource_total + tool_total

    passed = resource_passed + tool_passed

    print(f"\nTOTAL     : {passed}/{total}")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED")
    else:
        print("\n⚠ SOME TESTS FAILED")


if __name__ == "__main__":
    asyncio.run(main())