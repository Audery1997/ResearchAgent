from typing import TypedDict

from langgraph.graph import (
    StateGraph,
    START,
    END,
)


# ============================================================
# 1. STATE
# ============================================================

class ResearchState(TypedDict):

    question: str

    file_checked: bool

    validation_status: str

    final_answer: str


# ============================================================
# 2. NODE: inspect
# ============================================================

def inspect_node(
    state: ResearchState,
):

    print()
    print("[NODE] inspect")

    print(
        "Question:",
        state["question"],
    )

    # This is only a demonstration.
    # No real NetCDF access yet.

    return {
        "file_checked": True
    }


# ============================================================
# 3. NODE: validate
# ============================================================
def validate_node(
    state: ResearchState,
):

    print()
    print("[NODE] validate")

    if state["file_checked"]:

        return {
            "validation_status": "PASS"
        }


# ============================================================
# 4. CONDITIONAL ROUTER
# ============================================================

def route_after_validation(
    state: ResearchState,
):

    print()
    print(
        "[ROUTER] validation =",
        state["validation_status"],
    )

    if (
        state["validation_status"]
        == "PASS"
    ):

        return "respond"

    return "blocked"


# ============================================================
# 5. NODE: respond
# ============================================================

def respond_node(
    state: ResearchState,
):

    print()
    print("[NODE] respond")

    return {
        "final_answer":
            "The scientific workflow "
            "passed validation."
    }


# ============================================================
# 6. NODE: blocked
# ============================================================

def blocked_node(
    state: ResearchState,
):

    print()
    print("[NODE] blocked")

    return {
        "final_answer":
            "The scientific workflow "
            "failed validation and "
            "was blocked."
    }


# ============================================================
# 7. BUILD GRAPH
# ============================================================

builder = StateGraph(
    ResearchState
)


# Add nodes

builder.add_node(
    "inspect",
    inspect_node,
)

builder.add_node(
    "validate",
    validate_node,
)

builder.add_node(
    "respond",
    respond_node,
)

builder.add_node(
    "blocked",
    blocked_node,
)


# ============================================================
# 8. EDGES
# ============================================================

builder.add_edge(
    START,
    "inspect",
)

builder.add_edge(
    "inspect",
    "validate",
)


# ============================================================
# 9. CONDITIONAL EDGE
# ============================================================

builder.add_conditional_edges(
    "validate",
    route_after_validation,
    {
        "respond": "respond",
        "blocked": "blocked",
    },
)


builder.add_edge(
    "respond",
    END,
)

builder.add_edge(
    "blocked",
    END,
)


# ============================================================
# 10. COMPILE
# ============================================================

graph = builder.compile()


# ============================================================
# 11. RUN
# ============================================================

if __name__ == "__main__":

    initial_state = {
        "question":
            "Calculate Arctic temperature.",

        "file_checked":
            False,

        "validation_status":
            "NOT_RUN",

        "final_answer":
            "",
    }

    result = graph.invoke(
        initial_state
    )

    print()
    print("=" * 60)
    print("FINAL GRAPH STATE")
    print("=" * 60)

    print(result)