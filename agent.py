from config import MODEL, client
from validators import validate_tool_result
import json
from provenance import RunRecorder
from tools import (
    list_research_files,
    inspect_netcdf,
    area_weighted_mean,
)

# ============================================================
# Tool registry
# ============================================================

TOOLS = {
    "list_research_files": list_research_files,
    "inspect_netcdf": inspect_netcdf,
    "area_weighted_mean": area_weighted_mean,
}

# ============================================================
# System instructions
# ============================================================

SYSTEM_PROMPT = """
You are ResearchAgent, a scientific research automation agent.

Your goal is to assist with reproducible scientific research.

Important rules:

1. When the user asks about files in the local research
   workspace, you must use the available tools.

2. Never invent filenames, paths, variables, datasets,
   numerical results, or scientific results.

3. Any statement about local files must be based on
   actual tool output.

4. You currently have read-only access.

5. Never claim that you created, changed, deleted,
   or executed anything unless a tool actually did so.

6. If a tool returns an error, report the error accurately.

7. Scientific reproducibility and traceability are more
   important than answering quickly.
8. When asked about the contents, variables, dimensions,
   coordinates, units, or time range of a NetCDF file,
   you must use inspect_netcdf.

9. Never infer NetCDF metadata from the filename.

10. Do not claim that a variable exists unless it is
    confirmed by inspect_netcdf.
11. When calculating a spatial mean from latitude-longitude
    climate data, use an appropriate scientific tool rather
    than performing the calculation mentally.

12. Do not claim that an area-weighted result is valid unless
    the tool confirms that the grid satisfies its assumptions.

13. If the tool rejects a grid because its geometry is not
    supported, report that limitation instead of substituting
    an unweighted mean.
14. Some scientific calculations have deterministic
    validators.

15. If validation status is PASS, the numerical result
    may be reported as having passed the implemented
    numerical checks.

16. If validation status is FAIL, do not present the tool
    result as an accepted scientific result.

17. If validation status is FAIL, do not substitute the
    validator's independently calculated reference value
    as the final scientific result.

18. A validator reference value is diagnostic information,
    not a replacement result.

19. When validation fails, clearly report that the
    calculation failed validation and identify which
    checks failed.

20. PASS verifies implementation consistency only.
    It does not prove that the scientific method or
    physical interpretation is appropriate.
"""


# ============================================================
# Agent loop
# ============================================================

def run_agent(
                    user_question: str,
                    recorder: RunRecorder,
                ) -> str:

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": user_question,
        },
    ]

    max_steps = 10

    for step in range(max_steps):

        print()
        print("=" * 60)
        print(f"AGENT STEP {step + 1}")
        print("=" * 60)

        # ----------------------------------------------------
        # Ask the LLM what to do next
        # ----------------------------------------------------

        response = client.chat(
            model=MODEL,
            messages=messages,
            tools=list(TOOLS.values()),
            think=False,
        )

        messages.append(response.message)

        tool_calls = response.message.tool_calls

        # ----------------------------------------------------
        # No tool call means the model wants to answer
        # ----------------------------------------------------

        if not tool_calls:

            return response.message.content

        # ----------------------------------------------------
        # Execute all requested tools
        # ----------------------------------------------------

        for tool_call in tool_calls:

            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments

            print()
            print("MODEL REQUESTED TOOL:")
            print(tool_name)

            print()
            print("ARGUMENTS:")
            print(arguments)

            function = TOOLS.get(tool_name)

            if function is None:

                tool_result = (
                    f"ERROR: Unknown tool requested: {tool_name}"
                )

            else:

                try:

                    tool_result = function(**arguments)

                except Exception as error:

                    tool_result = (
                        f"ERROR while executing "
                        f"{tool_name}: {error}"
                    )

            print()
            print("TOOL RESULT:")
            print(tool_result)
            # =================================================
            # Deterministic scientific validation
            # =================================================

            validation_report = validate_tool_result(
                tool_name=tool_name,
                arguments=arguments,
                tool_result=str(tool_result),
            )
            recorder.record_tool(
                                    tool_name=tool_name,
                                    arguments=arguments,
                                    tool_result=str(
                                        tool_result
                                    ),
                                    validation_report=(
                                        validation_report
                                    ),
                                )
            validation_status = None

            if validation_report is not None:

                try:

                    validation_data = json.loads(
                        validation_report
                    )

                    validation_status = (
                        validation_data.get("status")
                    )

                except Exception:

                    validation_status = "FAIL"

            if validation_report is not None:

                print()
                print("VALIDATION REPORT:")
                print(validation_report)
            # ------------------------------------------------
            # Give the real-world observation back to the LLM
            # ------------------------------------------------

            # =================================================
            # Build the observation returned to the LLM
            # =================================================

            if validation_report is None:

                message_content = (
                    str(tool_result)
                )

            elif validation_status == "PASS":

                message_content = (
                    "SCIENTIFIC TOOL RESULT:\n"
                    f"{tool_result}\n\n"
                    "VALIDATION STATUS: PASS\n\n"
                    "DETERMINISTIC VALIDATION REPORT:\n"
                    f"{validation_report}\n\n"
                    "The result passed deterministic "
                    "validation and may be reported."
                )

            else:

                failed_checks = []

                if validation_report is not None:

                    try:

                        validation_data = json.loads(
                            validation_report
                        )

                        checks = validation_data.get(
                            "checks",
                            {}
                        )

                        failed_checks = [
                            name
                            for name, passed
                            in checks.items()
                            if passed is False
                        ]

                        absolute_difference = (
                            validation_data.get(
                                "absolute_difference"
                            )
                        )

                    except Exception:

                        failed_checks = [
                            "validator_report_parsing"
                        ]

                        absolute_difference = None

                failure_summary = {
                    "validation_status": "FAIL",
                    "tool_name": tool_name,
                    "failed_checks": failed_checks,
                    "absolute_difference": absolute_difference,
                }

                message_content = (
                    "SCIENTIFIC CALCULATION BLOCKED.\n\n"
                    "The deterministic validator returned FAIL.\n\n"
                    f"{json.dumps(failure_summary, indent=2)}\n\n"
                    "The numerical tool result is intentionally hidden "
                    "because it failed validation.\n\n"
                    "Do not provide a numerical scientific result. "
                    "Explain that validation failed and identify the "
                    "failed checks."
                )

            messages.append(
                {
                    "role": "tool",
                    "tool_name": tool_name,
                    "content": message_content,
                }
            )

    return (
        "ERROR: Agent exceeded the maximum "
        "number of execution steps."
    )


# ============================================================
# Command-line interface
# ============================================================

def read_multiline_question():
    """
    Read a multi-line research question from the terminal.

    Commands:
        /send  Submit the current question.
        /exit  Exit ResearchAgent.
    """

    print()
    print("=" * 60)
    print("RESEARCHAGENT")
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

        if len(lines) == 0:
            prompt = "> "
        else:
            prompt = "| "

        try:
            line = input(prompt)

        except EOFError:
            return None

        command = line.strip().lower()

        # ----------------------------------------------------
        # Exit
        # ----------------------------------------------------

        if command == "/exit":
            return None

        # ----------------------------------------------------
        # Submit
        # ----------------------------------------------------

        if command == "/send":

            question = "\n".join(lines).strip()

            if not question:

                print(
                    "No question entered. "
                    "Please type a question first."
                )

                continue

            return question

        # ----------------------------------------------------
        # Normal text
        # ----------------------------------------------------

        lines.append(line)


if __name__ == "__main__":

    while True:

        question = read_multiline_question()

        if question is None:

            print()
            print("ResearchAgent stopped.")

            break

        recorder = RunRecorder(
            request=question,
            model=MODEL,
            system_prompt=SYSTEM_PROMPT,
        )

        try:

            final_answer = run_agent(
                question,
                recorder,
            )

            recorder.record_final_answer(
                final_answer
            )

            recorder.finish(
                status="completed"
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

        print()
        print("=" * 60)
        print("FINAL ANSWER")
        print("=" * 60)
        print(final_answer)

        print()
        print(
            "RUN RECORD SAVED TO:"
        )
        print(
            recorder.run_dir
        )

        print()
