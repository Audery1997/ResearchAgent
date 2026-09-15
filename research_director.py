from __future__ import annotations

from datetime import datetime
from pathlib import Path

import argparse
import json
import sys

from codex_worker import (
    run_codex_research_worker,
)

from research_cycle import (
    run_review_cycle,
)


# ============================================================
# Project paths
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
)


# ============================================================
# Read task
# ============================================================

def read_task_file(
    task_file: str | Path,
) -> str:

    task_file = Path(
        task_file
    ).resolve()

    if not task_file.is_file():

        raise FileNotFoundError(
            f"Task file does not exist: "
            f"{task_file}"
        )

    task = task_file.read_text(
        encoding="utf-8"
    ).strip()

    if not task:

        raise ValueError(
            "Research task is empty."
        )

    return task


# ============================================================
# Final director summary
# ============================================================

def build_final_summary(
    run_dir: Path,
    worker_result: dict,
    cycle_result: dict,
):

    report_file = (
        run_dir
        / "analysis_report.md"
    )

    metrics_file = (
        run_dir
        / "results"
        / "metrics.json"
    )

    figure_dir = (
        run_dir
        / "figures"
    )

    script_dir = (
        run_dir
        / "scripts"
    )

    figures = sorted(
        str(path)
        for path in figure_dir.glob(
            "*.png"
        )
    )

    scripts = sorted(
        str(path)
        for path in script_dir.glob(
            "*.py"
        )
    )

    summary = {
        "director_status":
            cycle_result.get(
                "status"
            ),

        "run_id":
            worker_result.get(
                "run_id"
            ),

        "run_dir":
            str(
                run_dir
            ),

        "analysis_report":
            (
                str(report_file)
                if report_file.is_file()
                else None
            ),

        "metrics":
            (
                str(metrics_file)
                if metrics_file.is_file()
                else None
            ),

        "figures":
            figures,

        "scripts":
            scripts,

        "review_history":
            cycle_result.get(
                "history",
                [],
            ),

        "worker_return_code":
            worker_result.get(
                "return_code"
            ),

        "initial_artifact_validation":
            worker_result.get(
                "validation"
            ),
    }

    return summary


# ============================================================
# Research Director
# ============================================================

def run_research_director(
    task: str,
    source_files: list[str],
    max_revisions: int = 3,
):

    print()
    print("=" * 78)
    print("RESEARCH DIRECTOR")
    print("=" * 78)

    print()
    print("Research task:")
    print(task)

    print()
    print("Source files:")

    for file_name in source_files:

        print(
            f"  - {file_name}"
        )

    print()


    # ========================================================
    # STAGE 1 — Autonomous Researcher
    # ========================================================

    print()
    print("#" * 78)
    print("STAGE 1 — AUTONOMOUS RESEARCH")
    print("#" * 78)

    worker_result = (
        run_codex_research_worker(
            task=task,
            source_files=source_files,
        )
    )


    run_dir = Path(
        worker_result[
            "run_dir"
        ]
    ).resolve()


    # ========================================================
    # Worker process itself failed
    # ========================================================

    if (
        worker_result[
            "return_code"
        ]
        != 0
    ):

        final = {
            "director_status":
                "WORKER_FAILED",

            "run_dir":
                str(
                    run_dir
                ),

            "worker_result":
                worker_result,
        }

        (
            run_dir
            / "director_summary.json"
        ).write_text(
            json.dumps(
                final,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return final


    # ========================================================
    # Artifact contract failed
    # ========================================================

    artifact_status = (
        worker_result[
            "validation"
        ][
            "status"
        ]
    )

    if artifact_status != "PASS":

        final = {
            "director_status":
                "ARTIFACT_VALIDATION_FAILED",

            "run_dir":
                str(
                    run_dir
                ),

            "worker_result":
                worker_result,
        }

        (
            run_dir
            / "director_summary.json"
        ).write_text(
            json.dumps(
                final,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return final


    # ========================================================
    # STAGE 2 — Independent review / revision cycle
    # ========================================================

    print()
    print("#" * 78)
    print("STAGE 2 — SCIENTIFIC REVIEW CYCLE")
    print("#" * 78)


    cycle_result = (
        run_review_cycle(
            run_dir=run_dir,
            max_revision_rounds=(
                max_revisions
            ),
        )
    )


    # ========================================================
    # STAGE 3 — Final accepted research package
    # ========================================================

    final = build_final_summary(
        run_dir=run_dir,
        worker_result=worker_result,
        cycle_result=cycle_result,
    )


    (
        run_dir
        / "director_summary.json"
    ).write_text(
        json.dumps(
            final,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


    return final


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    parser = (
        argparse.ArgumentParser(
            description=(
                "Run an autonomous scientific "
                "research + review workflow."
            )
        )
    )


    parser.add_argument(
        "--task-file",
        required=True,
        help=(
            "UTF-8 text/Markdown file containing "
            "the research task."
        ),
    )


    parser.add_argument(
        "--source",
        nargs="+",
        required=True,
        help=(
            "Input files relative to "
            "ResearchAgent/workspace."
        ),
    )


    parser.add_argument(
        "--max-revisions",
        type=int,
        default=3,
    )


    args = parser.parse_args()


    try:

        task = read_task_file(
            args.task_file
        )

        result = (
            run_research_director(
                task=task,
                source_files=(
                    args.source
                ),
                max_revisions=(
                    args.max_revisions
                ),
            )
        )

    except Exception as error:

        print()
        print(
            "RESEARCH DIRECTOR FAILED"
        )

        print(
            f"{type(error).__name__}: "
            f"{error}"
        )

        sys.exit(1)


    print()
    print("=" * 78)
    print("FINAL DIRECTOR RESULT")
    print("=" * 78)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


    if (
        result.get(
            "director_status"
        )
        == "ACCEPTED"
    ):

        print()
        print(
            "Research workflow completed "
            "and passed independent review."
        )