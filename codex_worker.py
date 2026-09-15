from __future__ import annotations

from datetime import datetime
from pathlib import Path

import hashlib
import json
import shutil
import subprocess


# ============================================================
# Project directories
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
)

WORKSPACE_ROOT = (
    PROJECT_ROOT
    / "workspace"
)

CODEX_RUNS_ROOT = (
    WORKSPACE_ROOT
    / "codex_runs"
)


# ============================================================
# Locate Codex executable
# ============================================================

def find_codex_executable() -> Path:
    """
    Find Codex CLI.

    Priority:
    1. PATH
    2. latest VS Code ChatGPT extension installation
    """

    # --------------------------------------------------------
    # PATH
    # --------------------------------------------------------

    from_path = shutil.which(
        "codex"
    )

    if from_path:

        return Path(
            from_path
        ).resolve()

    # --------------------------------------------------------
    # VS Code ChatGPT extension
    # --------------------------------------------------------

    extensions_dir = (
        Path.home()
        / ".vscode"
        / "extensions"
    )

    candidates = list(
        extensions_dir.glob(
            "openai.chatgpt-*-win32-x64/"
            "bin/windows-x86_64/"
            "codex.exe"
        )
    )

    if not candidates:

        raise FileNotFoundError(
            "Could not locate codex.exe."
        )

    # newest extension first
    candidates.sort(
        key=lambda path:
            path.stat().st_mtime,
        reverse=True,
    )

    return candidates[0].resolve()


# ============================================================
# File fingerprint
# ============================================================

def sha256_file(
    path: Path,
) -> str:

    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


# ============================================================
# Create isolated Codex research workspace
# ============================================================

def create_codex_run(
    source_files: list[str],
):

    CODEX_RUNS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_id = (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y%m%d_%H%M%S_%f"
        )
    )

    run_dir = (
        CODEX_RUNS_ROOT
        / run_id
    )

    input_dir = (
        run_dir
        / "input"
    )

    scripts_dir = (
        run_dir
        / "scripts"
    )

    figures_dir = (
        run_dir
        / "figures"
    )

    results_dir = (
        run_dir
        / "results"
    )

    for directory in [
        input_dir,
        scripts_dir,
        figures_dir,
        results_dir,
    ]:

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    # --------------------------------------------------------
    # For our first experiment, copy small input files.
    #
    # Later, large CMIP6 data will NOT be copied.
    # --------------------------------------------------------

    input_manifest = []

    for relative_file in source_files:

        source = (
            WORKSPACE_ROOT
            / relative_file
        ).resolve()

        try:

            source.relative_to(
                WORKSPACE_ROOT
            )

        except ValueError:

            raise ValueError(
                "Input file must be "
                "inside workspace."
            )

        if not source.is_file():

            raise FileNotFoundError(
                source
            )

        destination = (
            input_dir
            / source.name
        )

        shutil.copy2(
            source,
            destination,
        )

        input_manifest.append(
            {
                "original_path":
                    relative_file,

                "copied_path":
                    str(
                        destination.relative_to(
                            run_dir
                        )
                    ),

                "size_bytes":
                    destination.stat().st_size,

                "sha256":
                    sha256_file(
                        destination
                    ),
            }
        )

    return (
        run_id,
        run_dir,
        input_manifest,
    )


# ============================================================
# Output contract
# ============================================================

def validate_codex_outputs(
    run_dir: Path,
):

    errors = []

    report = (
        run_dir
        / "analysis_report.md"
    )

    metrics = (
        run_dir
        / "results"
        / "metrics.json"
    )

    figures = list(
        (
            run_dir
            / "figures"
        ).glob(
            "*.png"
        )
    )

    scripts = list(
        (
            run_dir
            / "scripts"
        ).glob(
            "*.py"
        )
    )

    if not report.is_file():

        errors.append(
            "analysis_report.md missing"
        )

    if not metrics.is_file():

        errors.append(
            "results/metrics.json missing"
        )

    else:

        try:

            json.loads(
                metrics.read_text(
                    encoding="utf-8"
                )
            )

        except Exception as error:

            errors.append(
                "metrics.json is invalid JSON: "
                f"{error}"
            )

    if len(figures) < 2:

        errors.append(
            "Fewer than two PNG figures produced"
        )

    if not scripts:

        errors.append(
            "No reproducible Python scripts produced"
        )

    return {
        "status":
            (
                "PASS"
                if not errors
                else "FAIL"
            ),

        "errors":
            errors,

        "report":
            (
                str(report)
                if report.exists()
                else None
            ),

        "figures":
            [
                str(path)
                for path in figures
            ],

        "scripts":
            [
                str(path)
                for path in scripts
            ],

        "metrics":
            (
                str(metrics)
                if metrics.exists()
                else None
            ),
    }


# ============================================================
# Codex Research Worker
# ============================================================

def run_codex_research_worker(
    task: str,
    source_files: list[str],
    timeout_seconds: int = 3600,
):

    codex = (
        find_codex_executable()
    )

    (
        run_id,
        run_dir,
        input_manifest,
    ) = create_codex_run(
        source_files
    )

    # ========================================================
    # Worker contract
    # ========================================================

    instructions = f"""
You are an autonomous scientific research coding worker.

You are working inside an isolated research workspace.

USER RESEARCH TASK
==================

{task}


AVAILABLE INPUT DATA
====================

Input files are located under:

input/


YOUR RESPONSIBILITIES
=====================

You must independently:

1. Inspect the input scientific data.

2. Decide which 2-3 diagnostics are scientifically useful
   for answering or exploring the research task.

3. Write reproducible Python analysis scripts.

4. Execute those scripts yourself.

5. Diagnose and fix errors if execution fails.

6. Generate at least TWO publication-quality PNG figures.

7. Save quantitative results in:

   results/metrics.json

8. Save all Python analysis code under:

   scripts/

9. Save figures under:

   figures/

10. Write a scientific analysis report:

   analysis_report.md


ANALYSIS REPORT REQUIREMENTS
============================

analysis_report.md must contain:

- Research question
- Dataset inspection
- Methods
- Quantitative results
- Figure descriptions
- Scientific interpretation
- Limitations and caveats
- Files generated


SCIENTIFIC RULES
================

- Never invent numerical results.

- Numerical claims must come from executed code.

- Preserve units.

- Inspect dimensions and metadata before analysis.

- For latitude-longitude climate data, use scientifically
  appropriate spatial weighting.

- Distinguish numerical evidence from interpretation.

- Do not claim causal mechanisms unsupported by the data.

- If the dataset is insufficient to answer part of the
  research question, state that explicitly.


SAFETY / FILE RULES
===================

- Do NOT modify files under input/.

- Do NOT modify files outside the current working directory.

- Do NOT modify the parent ResearchAgent repository.

- Do NOT use the network.

- All generated work must remain inside this directory.


COMPLETION CONDITION
====================

Do not finish until:

- scripts contain reproducible analysis code;
- at least two figures exist;
- results/metrics.json is valid JSON;
- analysis_report.md exists;
- the scripts have actually been run successfully.
"""

    (
        run_dir
        / "TASK.md"
    ).write_text(
        instructions,
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print("CODEX RESEARCH WORKER")
    print("=" * 70)

    print(
        "Codex executable:",
        codex,
    )

    print(
        "Research run:",
        run_dir,
    )

    print()

    # ========================================================
    # Run Codex
    # ========================================================

    process = subprocess.run(
        [
            str(codex),
            "exec",
            instructions,
        ],

        cwd=run_dir,

        capture_output=True,

        text=True,

        encoding="utf-8",

        errors="replace",

        timeout=timeout_seconds,
    )

    # ========================================================
    # Preserve Codex logs
    # ========================================================

    (
        run_dir
        / "codex_stdout.log"
    ).write_text(
        process.stdout,
        encoding="utf-8",
    )

    (
        run_dir
        / "codex_stderr.log"
    ).write_text(
        process.stderr,
        encoding="utf-8",
    )

    # ========================================================
    # Validate output contract
    # ========================================================

    validation = (
        validate_codex_outputs(
            run_dir
        )
    )

    # ========================================================
    # Provenance
    # ========================================================

    metadata = {
        "run_id":
            run_id,

        "codex_executable":
            str(codex),

        "codex_return_code":
            process.returncode,

        "input_manifest":
            input_manifest,

        "output_validation":
            validation,
    }

    (
        run_dir
        / "worker_run.json"
    ).write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return {
        "run_id":
            run_id,

        "run_dir":
            str(run_dir),

        "return_code":
            process.returncode,

        "validation":
            validation,
    }


# ============================================================
# Standalone first experiment
# ============================================================

if __name__ == "__main__":

    result = (
        run_codex_research_worker(
            task="""
Treat test_climate.nc as an unfamiliar climate dataset.

Independently inspect the dataset and perform an exploratory
scientific analysis.

Choose 2-3 diagnostics that are appropriate for the available
variables and dimensions.

Generate at least two publication-style figures and explain
what can and cannot be concluded from this dataset.

Do not rely on any predefined ResearchAgent climate-analysis
functions.
""",

            source_files=[
                "test_climate.nc"
            ],
        )
    )

    print()
    print("=" * 70)
    print("WORKER RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )