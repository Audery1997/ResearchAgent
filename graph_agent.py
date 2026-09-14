import json
from typing import TypedDict
from checkpointing import (
    create_checkpointer,
)
from langgraph.graph import (
    StateGraph,
    START,
    END,
)
from langgraph.types import (
    interrupt,
    Command,
)

from config import MODEL, client

from tools import (
    list_research_files,
    inspect_netcdf,
    area_weighted_mean,
    subtract_step_results,
)

from validators import validate_tool_result

from provenance import RunRecorder

from planner import (
    create_research_plan,
)


# ============================================================
# Tool registry
# ============================================================

TOOLS = {
    "list_research_files":
        list_research_files,

    "inspect_netcdf":
        inspect_netcdf,

    "area_weighted_mean":
        area_weighted_mean,

    "subtract_step_results":
        subtract_step_results,
}


# ============================================================
# System prompt
# ============================================================

SYSTEM_PROMPT = """
You are ResearchAgent, a scientific research automation agent.

Your goal is to assist with reproducible scientific research.

Important rules:

1. When the user asks about files in the local research
   workspace, use the available tools.

2. Never invent filenames, paths, variables, datasets,
   numerical results, or scientific results.

3. Any statement about local files must be based on
   actual tool output.

4. You currently have read-only access.

5. Never claim that you created, changed, deleted,
   or executed something unless a tool actually did so.

6. If a tool returns an error, report it accurately.

7. Scientific reproducibility and traceability are more
   important than answering quickly.

8. When asked about NetCDF variables, dimensions,
   coordinates, units, or time range, use inspect_netcdf.

9. Never infer NetCDF metadata from a filename.

10. Do not claim that a variable exists unless confirmed
    by inspect_netcdf or another scientific tool.

11. For spatial means from latitude-longitude climate data,
    use an appropriate scientific tool.

12. If deterministic validation returns FAIL, do not report
    the numerical result as an accepted scientific result.

13. Do not substitute a validator reference value for a
    failed scientific result.

14. PASS verifies numerical implementation consistency only.
    It does not prove that the scientific interpretation
    is physically appropriate.
"""


# ============================================================
# 1. STATE
# ============================================================

class ResearchState(TypedDict):

    # Original user request
    question: str

    research_plan: dict

    completed_step_ids: list[int]

    current_step: dict | None

    step_outputs: dict

    selection_status: str

    # Conversation passed to Ollama
    messages: list



    # Results produced by execute_tool_node
    tool_executions: list

    execution_errors: list

    execution_error_type: str | None

    # Validation failures in current cycle
    validation_failures: list

    # Final text answer
    final_answer: str

    # Safety against infinite loops
    step_count: int


def planner_node(
    state: ResearchState,
):
    """
    Convert the user's research request into
    an explicit structured scientific plan.
    """

    print()
    print("=" * 60)
    print("[NODE] PLANNER")
    print("=" * 60)

    plan = create_research_plan(
        state["question"]
    )

    print()
    print("RESEARCH PLAN:")

    print(
        json.dumps(
            plan,
            indent=2,
            ensure_ascii=False,
        )
    )

    messages = list(
        state["messages"]
    )

    messages.append(
        {
            "role": "system",
            "content": (
                "The following research plan has been "
                "approved for this task:\n\n"
                f"{json.dumps(plan, indent=2, ensure_ascii=False)}\n\n"
                "Use this plan to guide tool execution. "
                "Do not claim that a step is complete until "
                "the required tool has actually executed."
            ),
        }
    )

    return {
        "research_plan": plan,
        "messages": messages,
    }


# ============================================================
# 2. REPORTER NODE
# ============================================================

def reporter_node(
    state: ResearchState,
):
    """
    Produce the final answer only after
    the approved research plan is complete.
    """

    print()
    print("=" * 60)
    print("[NODE] REPORTER")
    print("=" * 60)

    messages = list(
        state["messages"]
    )

    messages.append(
        {
            "role": "system",
            "content": (
                "The approved research plan has "
                "completed successfully. "
                "Report only results supported by "
                "successful tool execution and validation."
            ),
        }
    )

    response = client.chat(
        model=MODEL,
        messages=messages,
        think=False,
    )

    return {
        "final_answer":
            response.message.content
            or ""
    }


def select_next_step_node(
    state: ResearchState,
):
    """
    Select the next executable step whose dependencies
    have all completed successfully.
    """

    print()
    print("=" * 60)
    print("[NODE] SELECT NEXT STEP")
    print("=" * 60)

    completed = set(
        state["completed_step_ids"]
    )

    steps = (
        state["research_plan"]
        .get(
            "steps",
            [],
        )
    )

    remaining = [
        step
        for step in steps
        if step["step_id"]
        not in completed
    ]

    # ========================================================
    # Entire DAG completed
    # ========================================================

    if not remaining:

        print(
            "All planned steps are complete."
        )

        return {
            "current_step":
                None,

            "selection_status":
                "COMPLETE",
        }

    # ========================================================
    # Find first READY step
    # ========================================================

    for step in remaining:

        dependencies = set(
            step.get(
                "depends_on",
                [],
            )
        )

        if dependencies.issubset(
            completed
        ):

            print(
                f"Next ready step: "
                f"{step['step_id']} "
                f"{step['tool_name']} "
                f"depends_on="
                f"{step.get('depends_on', [])}"
            )

            return {
                "current_step":
                    step,

                "selection_status":
                    "READY",

                "execution_error_type":
                    None,

                "step_count":
                    0,
            }

    # ========================================================
    # Remaining steps exist, but none can execute.
    #
    # This indicates a broken dependency graph.
    # ========================================================

    print(
        "[CONTROL] DAG dependency deadlock."
    )

    return {
        "current_step":
            None,

        "selection_status":
            "DEADLOCK",
    }


def route_after_step_selection(
    state: ResearchState,
):

    status = state[
        "selection_status"
    ]

    if status == "READY":

        return "execute"

    if status == "COMPLETE":

        return "report"

    return "blocked"


def execute_tool_node(
    state: ResearchState,
):

    print()
    print("=" * 60)
    print("[NODE] EXECUTE TOOL")
    print("=" * 60)

    step = state["current_step"]

    if step is None:

        return {
            "tool_executions": []
        }

    tool_name = step[
        "tool_name"
    ]

    arguments = step[
        "arguments"
    ]

    print(
        "Executing planned step:",
        step["step_id"],
    )

    print(
        "Tool:",
        tool_name,
    )

    print(
        "Arguments:",
        arguments,
    )

    function = TOOLS.get(
        tool_name
    )

    status = "SUCCESS"
    error_message = None
    tool_result = ""

    if function is None:

        status = "ERROR"

        error_message = (
            f"Unknown tool: {tool_name}"
        )

    else:

        try:

            if (
                tool_name
                == "subtract_step_results"
            ):

                raw_result = function(
                    **arguments,
                    step_outputs=state[
                        "step_outputs"
                    ],
                )

            else:

                raw_result = function(
                    **arguments
                )

            tool_result = str(
                raw_result
            )

            if (
                tool_result
                .lstrip()
                .startswith("ERROR")
            ):

                status = "ERROR"

                error_message = (
                    tool_result
                )

        except Exception as error:

            status = "ERROR"

            error_message = (
                f"{type(error).__name__}: "
                f"{error}"
            )

    execution = {
        "step_id":
            step["step_id"],

        "tool_name":
            tool_name,

        "arguments":
            arguments,

        "status":
            status,

        "tool_result":
            tool_result,

        "error":
            error_message,
    }

    if status == "SUCCESS":

        print()
        print("TOOL RESULT:")
        print(tool_result)

    else:

        print()
        print("TOOL EXECUTION ERROR:")
        print(error_message)

    messages = list(
        state["messages"]
    )

    messages.append(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                },
            ],
        }
    )

    return {
        "tool_executions": [
            execution
        ],
        "messages": messages,
        "step_count": state["step_count"] + 1,
    }


def classify_execution_error(
    error_message: str,
) -> str:

    text = (
        error_message
        or ""
    ).lower()

    if (
        "file does not exist"
        in text
        or "file not found"
        in text
        or "filenotfounderror"
        in text
        or "no such file or directory"
        in text
        or "folder does not exist"
        in text
    ):

        return "USER_INPUT_REQUIRED"

    if (
        "unexpected keyword argument"
        in text
        or "missing required"
        in text
        or "required positional argument"
        in text
        or "required keyword-only argument"
        in text
    ):

        return "RECOVERABLE"

    return "FATAL"

def build_tool_message(
    execution: dict,
    validation_report,
):
    """
    Construct the observation that will be sent back
    to the LLM.

    FAIL results are hidden behind a hard gate.
    """

    tool_name = execution[
        "tool_name"
    ]

    tool_result = execution[
        "tool_result"
    ]

    # --------------------------------------------------------
    # Tool without validator
    # --------------------------------------------------------

    if validation_report is None:

        return (
            str(tool_result),
            None,
        )

    # --------------------------------------------------------
    # Parse validator result
    # --------------------------------------------------------

    try:

        validation_data = json.loads(
            validation_report
        )

    except Exception:

        return (
            (
                "SCIENTIFIC CALCULATION BLOCKED.\n"
                "The validation report could not "
                "be parsed."
            ),
            {
                "tool_name":
                    tool_name,

                "status":
                    "FAIL",

                "failed_checks": [
                    "validation_report_parsing"
                ],
            },
        )

    status = validation_data.get(
        "status"
    )

    # --------------------------------------------------------
    # PASS
    # --------------------------------------------------------

    if status == "PASS":

        message = (
            "SCIENTIFIC TOOL RESULT:\n"
            f"{tool_result}\n\n"
            "VALIDATION STATUS: PASS\n\n"
            "The result passed the implemented "
            "deterministic validation checks."
        )

        return (
            message,
            None,
        )

    # --------------------------------------------------------
    # FAIL
    #
    # Do not expose failed numerical result or independent
    # reference value to reporting LLM.
    # --------------------------------------------------------

    checks = validation_data.get(
        "checks",
        {},
    )

    failed_checks = [
        name
        for name, passed
        in checks.items()
        if passed is False
    ]

    failure = {
        "tool_name":
            tool_name,

        "status":
            "FAIL",

        "failed_checks":
            failed_checks,

        "absolute_difference":
            validation_data.get(
                "absolute_difference"
            ),
    }

    message = (
        "SCIENTIFIC CALCULATION BLOCKED.\n\n"
        "The deterministic validator returned FAIL.\n\n"
        f"{json.dumps(failure, indent=2)}\n\n"
        "The failed numerical result has been hidden.\n"
        "Do not provide a numerical scientific result."
    )

    return (
        message,
        failure,
    )


# ============================================================
# 6. VALIDATE NODE FACTORY
# ============================================================

def make_validate_node(
    recorder: RunRecorder,
):
    """
    Create a validation node with access to
    this run's provenance recorder.
    """

    def validate_node(
        state: ResearchState,
    ):

        print()
        print("=" * 60)
        print("[NODE] VALIDATE")
        print("=" * 60)

        messages = list(
            state["messages"]
        )

        failures = []

        execution_errors = []

        error_type = None

        completed_step_ids = list(
            state["completed_step_ids"]
        )

        step_outputs = dict(
            state["step_outputs"]
        )

        for execution in state[
            "tool_executions"
        ]:

            if execution[
                "status"
            ] == "ERROR":

                error_type = classify_execution_error(
                    execution["error"]
                )

                execution_error = {
                    "step_id":
                        execution["step_id"],

                    "error_type":
                        error_type,
                    "tool_name":
                        execution[
                            "tool_name"
                        ],

                    "arguments":
                        execution[
                            "arguments"
                        ],

                    "error":
                        execution[
                            "error"
                        ],
                }

                execution_errors.append(
                    execution_error
                )

                messages.append(
                    {
                        "role": "tool",

                        "tool_name":
                            execution[
                                "tool_name"
                            ],

                        "content": (
                            "TOOL EXECUTION FAILED.\n\n"
                            f"{json.dumps(execution_error, indent=2, ensure_ascii=False)}\n\n"
                            "The plan step is NOT complete. "
                            "The workflow will route this "
                            "error according to its classification."
                        ),
                    }
                )

                recorder.record_tool(
                    tool_name=execution[
                        "tool_name"
                    ],
                    arguments=execution[
                        "arguments"
                    ],
                    tool_result=(
                        "EXECUTION ERROR: "
                        + str(
                            execution[
                                "error"
                            ]
                        )
                    ),
                    validation_report=None,
                )

                continue

            tool_name = execution[
                "tool_name"
            ]

            arguments = execution[
                "arguments"
            ]

            tool_result = execution[
                "tool_result"
            ]

            # -----------------------------------------------
            # Deterministic validator
            # -----------------------------------------------

            validation_report = (
                validate_tool_result(
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_result=tool_result,
                    step_outputs=state[
                        "step_outputs"
                    ],
                )
            )

            if validation_report is not None:

                print()
                print(
                    "VALIDATION REPORT:"
                )

                print(
                    validation_report
                )

            # -----------------------------------------------
            # Record provenance
            # -----------------------------------------------

            recorder.record_tool(
                tool_name=tool_name,
                arguments=arguments,
                tool_result=tool_result,
                validation_report=(
                    validation_report
                ),
            )

            # -----------------------------------------------
            # Build safe observation for LLM
            # -----------------------------------------------

            message_content, failure = (
                build_tool_message(
                    execution,
                    validation_report,
                )
            )

            messages.append(
                {
                    "role":
                        "tool",

                    "tool_name":
                        tool_name,

                    "content":
                        message_content,
                }
            )

            if failure is not None:

                failures.append(
                    failure
                )

        if (
            state["tool_executions"]
            and not execution_errors
            and not failures
        ):

            current_step = state[
                "current_step"
            ]

            if current_step is not None:

                step_id = current_step[
                    "step_id"
                ]

                if (
                    step_id
                    not in completed_step_ids
                ):

                    completed_step_ids.append(
                        step_id
                    )

                    try:

                        parsed_result = json.loads(
                            execution[
                                "tool_result"
                            ]
                        )

                    except Exception:

                        parsed_result = execution[
                            "tool_result"
                        ]

                    step_outputs[
                        str(step_id)
                    ] = {
                        "tool_name":
                            execution[
                                "tool_name"
                            ],

                        "result":
                            parsed_result,

                        "validation_status":
                            (
                                "PASS"
                                if validation_report
                                is not None
                                else "NOT_APPLICABLE"
                            ),
                    }

        print()
        print("PLAN PROGRESS:")

        for plan_step in (
            state["research_plan"]
            .get(
                "steps",
                [],
            )
        ):

            step_id = plan_step[
                "step_id"
            ]

            tool_name = plan_step[
                "tool_name"
            ]

            if (
                step_id
                in completed_step_ids
            ):

                marker = "[DONE]"

            else:

                marker = "[PENDING]"

            print(
                f"{marker} "
                f"Step {step_id}: "
                f"{tool_name}"
            )

        return {
            "messages":
                messages,

            "execution_errors":
                execution_errors,

            "execution_error_type":
                error_type,

            "validation_failures":
                failures,

            "tool_executions":
                [],

            "completed_step_ids":
                completed_step_ids,

            "step_outputs":
                step_outputs,
        }

    return validate_node


# ============================================================
# 7. ROUTER AFTER VALIDATION
# ============================================================

def route_after_validation(
    state: ResearchState,
):

    if state[
        "validation_failures"
    ]:

        print()
        print(
            "[ROUTER] -> SCIENTIFIC BLOCK"
        )

        return "blocked"

    error_type = state.get(
        "execution_error_type"
    )

    if (
        error_type
        == "USER_INPUT_REQUIRED"
    ):

        print()
        print(
            "[ROUTER] -> USER INPUT REQUIRED"
        )

        return "needs_user_input"

    if (
        error_type
        == "RECOVERABLE"
    ):

        print()

        if state["step_count"] >= 3:

            print(
                "[ROUTER] -> RETRY LIMIT REACHED"
            )

            return "blocked"

        print(
            "[ROUTER] -> RETRY"
        )

        return "retry"

    if (
        error_type
        == "FATAL"
    ):

        print()
        print(
            "[ROUTER] -> BLOCK"
        )

        return "blocked"

    print()
    print(
        "[ROUTER] -> NEXT STEP"
    )

    return "next_step"


def needs_user_input_node(
    state: ResearchState,
):
    """
    Pause the workflow and request human input.

    The graph state is persisted by the checkpointer.
    """

    print()
    print("=" * 60)
    print("[NODE] NEEDS USER INPUT")
    print("=" * 60)

    errors = state.get(
        "execution_errors",
        [],
    )

    if not errors:

        interrupt(
            {
                "reason":
                    "additional_user_input_required",

                "message":
                    "The workflow requires "
                    "additional user input.",
            }
        )

        return {}

    latest = errors[-1]

    current_step = state[
        "current_step"
    ]

    old_file_path = (
        current_step
        .get(
            "arguments",
            {}
        )
        .get(
            "file_path"
        )
    )

    user_response = interrupt(
        {
            "reason":
                "file_not_found",

            "step_id":
                latest.get(
                    "step_id"
                ),

            "tool_name":
                latest.get(
                    "tool_name"
                ),

            "error":
                latest.get(
                    "error"
                ),

            "missing_file":
                old_file_path,

            "message": (
                "The requested file was not found. "
                "Please provide the correct file path "
                "relative to the workspace."
            ),
        }
    )

    new_file_path = str(
        user_response
    ).strip()

    if not new_file_path:

        return {
            "execution_error_type":
                "USER_INPUT_REQUIRED"
        }

    print()
    print(
        "[HUMAN INPUT] replacement file:",
        new_file_path,
    )

    plan = dict(
        state["research_plan"]
    )

    steps = [
        dict(step)
        for step
        in plan.get(
            "steps",
            [],
        )
    ]

    completed = set(
        state[
            "completed_step_ids"
        ]
    )

    for step in steps:

        if (
            step["step_id"]
            in completed
        ):
            continue

        arguments = dict(
            step.get(
                "arguments",
                {}
            )
        )

        if (
            arguments.get(
                "file_path"
            )
            == old_file_path
        ):

            arguments[
                "file_path"
            ] = new_file_path

            step[
                "arguments"
            ] = arguments

    plan[
        "steps"
    ] = steps

    messages = list(
        state["messages"]
    )

    messages.append(
        {
            "role": "user",
            "content": (
                "For the remaining plan steps, replace "
                f"file_path {json.dumps(old_file_path, ensure_ascii=False)} "
                f"with {json.dumps(new_file_path, ensure_ascii=False)}."
            ),
        }
    )

    return {
        "research_plan":
            plan,

        "messages":
            messages,

        "current_step":
            None,

        "execution_errors":
            [],

        "execution_error_type":
            None,
    }


def blocked_node(
    state: ResearchState,
):
    """
    Produce a deterministic blocked response.

    We deliberately do not ask the LLM to rewrite
    failed numerical results.
    """

    print()
    print("=" * 60)
    print("[NODE] BLOCKED")
    print("=" * 60)

    failures = state.get(
        "validation_failures",
        [],
    )

    if not failures:

        errors = state.get(
            "execution_errors",
            [],
        )

        if state.get("selection_status") == "DEADLOCK":

            answer = (
                "The research workflow was blocked by a "
                "DAG dependency deadlock. Remaining steps "
                "have unmet dependencies and cannot execute."
            )

        elif errors:

            latest = errors[-1]

            reason = (
                "The maximum number of execution attempts was reached."
                if latest.get("error_type") == "RECOVERABLE"
                else "A fatal tool execution error occurred."
            )

            answer = (
                f"The research workflow was blocked. {reason}\n\n"
                f"Step: {latest.get('step_id')}\n"
                f"Tool: {latest.get('tool_name')}\n"
                f"Error: {latest.get('error')}\n\n"
                "The planned step remains incomplete."
            )

        else:

            answer = (
                "The research workflow was blocked."
            )

    else:

        lines = [
            (
                "The scientific calculation "
                "failed deterministic validation "
                "and was blocked."
            ),
            "",
            "Failed checks:",
        ]

        for failure in failures:

            tool_name = failure.get(
                "tool_name",
                "unknown",
            )

            for check in failure.get(
                "failed_checks",
                [],
            ):

                lines.append(
                    f"- {tool_name}: {check}"
                )

            difference = failure.get(
                "absolute_difference"
            )

            if difference is not None:

                lines.append(
                    "- diagnostic absolute "
                    f"difference: {difference}"
                )

        lines.extend(
            [
                "",
                (
                    "No numerical result from "
                    "the failed calculation is "
                    "reported as scientifically "
                    "accepted."
                ),
            ]
        )

        answer = "\n".join(
            lines
        )

    return {
        "final_answer":
            answer
    }


# ============================================================
# 9. BUILD THE LANGGRAPH
# ============================================================

def build_graph(
    recorder: RunRecorder,
    checkpointer,
):

    builder = StateGraph(
        ResearchState
    )

    builder.add_node(
        "planner",
        planner_node,
    )

    builder.add_node(
        "select_next_step",
        select_next_step_node,
    )

    builder.add_node(
        "execute_tool",
        execute_tool_node,
    )

    builder.add_node(
        "validate",
        make_validate_node(
            recorder
        ),
    )

    builder.add_node(
        "reporter",
        reporter_node,
    )

    builder.add_node(
        "needs_user_input",
        needs_user_input_node,
    )

    builder.add_node(
        "blocked",
        blocked_node,
    )

    builder.add_edge(
        START,
        "planner",
    )

    builder.add_edge(
        "planner",
        "select_next_step",
    )

    builder.add_conditional_edges(
        "select_next_step",
        route_after_step_selection,
        {
            "report": "reporter",
            "execute": "execute_tool",
            "blocked": "blocked",
        },
    )

    builder.add_edge(
        "execute_tool",
        "validate",
    )

    builder.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "next_step": "select_next_step",
            "retry": "execute_tool",
            "needs_user_input": "needs_user_input",
            "blocked": "blocked",
        },
    )

    builder.add_edge(
        "reporter",
        END,
    )

    builder.add_edge(
        "needs_user_input",
        "select_next_step",
    )

    builder.add_edge(
        "blocked",
        END,
    )

    return builder.compile(
        checkpointer=checkpointer,
    )
                                


# ============================================================
# 10. MULTILINE CLI
# ============================================================

def read_multiline_question():

    print()
    print("=" * 60)
    print("RESEARCHAGENT — LANGGRAPH")
    print("=" * 60)

    print(
        "Enter your research question below.\n"
        "Multiple lines are supported.\n"
        "Type /send on a new line to submit.\n"
        "Type /exit on a new line to quit."
    )

    print()

    lines = []

    while True:

        prompt = (
            "> "
            if not lines
            else "| "
        )

        try:

            line = input(
                prompt
            )

        except EOFError:

            return None

        command = (
            line.strip().lower()
        )

        if command == "/exit":

            return None

        if command == "/send":

            question = (
                "\n".join(lines)
                .strip()
            )

            if question:

                return question

            print(
                "No question entered."
            )


            continue

        lines.append(
            line
        )


# ============================================================
# 11. MAIN
# ============================================================

if __name__ == "__main__":
    checkpoint_connection, checkpointer = (
        create_checkpointer()
    )
    try:
        while True:

            question = (
                read_multiline_question()
            )

            if question is None:

                print()
                print(
                    "ResearchAgent stopped."
                )

                break

            # ----------------------------------------------------
            # Create provenance recorder
            # ----------------------------------------------------

            recorder = RunRecorder(
                request=question,
                model=MODEL,
                system_prompt=SYSTEM_PROMPT,
            )

            thread_id = recorder.run_id

            recorder.metadata[
                "thread_id"
            ] = thread_id

            # ----------------------------------------------------
            # Build workflow
            # ----------------------------------------------------

            graph = build_graph(
                recorder,checkpointer,
            )
            print(
                    graph.get_graph()
                    .draw_mermaid()
                    )

            # ----------------------------------------------------
            # Initial State
            # ----------------------------------------------------

            initial_state = {
                "question":
                    question,

                "research_plan":
                    {},

                "completed_step_ids":
                    [],

                "step_outputs":
                    {},

                "selection_status":
                    "NOT_STARTED",

                "messages": [
                    {
                        "role":
                            "system",

                        "content":
                            SYSTEM_PROMPT,
                    },
                    {
                        "role":
                            "user",

                        "content":
                            question,
                    },
                ],

                "current_step":
                    None,

                "tool_executions":
                    [],

                "execution_errors":
                    [],

                "execution_error_type":
                    None,

                "validation_failures":
                    [],

                "final_answer":
                    "",

                "step_count":
                    0,
            }

            # ----------------------------------------------------
            # Run graph
            # ----------------------------------------------------

            try:

                config = {
                    "configurable": {
                        "thread_id": thread_id
                    }
                }

                result = graph.invoke(
                    initial_state,
                    config=config,
                )

                while result.get(
                    "__interrupt__"
                ):

                    print()
                    print("=" * 60)
                    print("WORKFLOW PAUSED")
                    print("=" * 60)

                    interrupts = result[
                        "__interrupt__"
                    ]

                    for item in interrupts:

                        print()
                        print(
                            "ResearchAgent requires "
                            "additional information."
                        )

                        try:

                            print(
                                json.dumps(
                                    item.value,
                                    indent=2,
                                    ensure_ascii=False,
                                )
                            )

                        except Exception:

                            print(
                                item
                            )

                    print()
                    print(
                        "Enter the requested information."
                    )

                    human_input = input(
                        "Resume > "
                    ).strip()

                    if not human_input:

                        print(
                            "Input cannot be empty. "
                            "The workflow remains paused."
                        )

                        continue

                    result = graph.invoke(
                        Command(
                            resume=human_input
                        ),
                        config=config,
                    )

                snapshot = graph.get_state(
                    config
                )

                final_answer = result[
                    "final_answer"
                ]

                recorder.record_final_answer(
                    final_answer
                )

                if (
                    result["validation_failures"]
                    or result["selection_status"] == "DEADLOCK"
                ):

                    run_status = "blocked"

                elif result["execution_error_type"] == "USER_INPUT_REQUIRED":

                    run_status = "needs_user_input"

                elif result["execution_errors"]:

                    run_status = "blocked"

                else:

                    run_status = "completed"

                recorder.finish(
                    status=run_status
                )

            except Exception as error:

                recorder.finish(
                    status="failed",
                    error=(
                        f"{type(error).__name__}: "
                        f"{error}"
                    ),
                )

                raise

            # ----------------------------------------------------
            # Final output
            # ----------------------------------------------------

            print()
            print("=" * 60)
            print("FINAL ANSWER")
            print("=" * 60)

            print(
                final_answer
            )

            print()
            print(
                "RUN RECORD SAVED TO:"
            )

            print(
                recorder.run_dir
            )

            print()
            print(
                "CHECKPOINT THREAD ID:"
            )
            print(
                thread_id
            )

            print()
            print(
                "NEXT GRAPH NODE(S):"
            )
            print(
                snapshot.next
            )
    finally:

        checkpoint_connection.close()
