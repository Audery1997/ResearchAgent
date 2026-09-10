from datetime import datetime
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

import hashlib
import json
import platform


# ============================================================
# Project paths
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent

WORKSPACE_ROOT = (
    PROJECT_ROOT / "workspace"
).resolve()

RUNS_ROOT = (
    PROJECT_ROOT / "runs"
).resolve()


# ============================================================
# Utilities
# ============================================================

def current_time():
    """
    Return local time with timezone information.
    """

    return datetime.now().astimezone().isoformat(
        timespec="seconds"
    )


def package_version(package_name: str):
    """
    Safely retrieve an installed package version.
    """

    try:
        return version(package_name)

    except PackageNotFoundError:
        return None


def write_json(
    path: Path,
    data,
):
    """
    Write JSON in a consistent format.
    """

    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )


# ============================================================
# Input file fingerprint
# ============================================================

def fingerprint_workspace_file(
    file_path: str,
    hash_limit_mb: int = 100,
):
    """
    Record identifying information about an input file.

    For files <= hash_limit_mb, calculate SHA256.
    Large climate files are not hashed automatically
    because this can be expensive.
    """

    target = (
        WORKSPACE_ROOT / file_path
    ).resolve()

    # Security boundary
    try:
        target.relative_to(
            WORKSPACE_ROOT
        )

    except ValueError:
        return {
            "path": file_path,
            "status": "outside_workspace",
        }

    if not target.is_file():
        return {
            "path": file_path,
            "status": "file_not_found",
        }

    stat = target.stat()

    information = {
        "path": str(
            target.relative_to(
                WORKSPACE_ROOT
            )
        ),
        "size_bytes": stat.st_size,
        "modified_time": datetime.fromtimestamp(
            stat.st_mtime
        ).astimezone().isoformat(
            timespec="seconds"
        ),
    }

    hash_limit_bytes = (
        hash_limit_mb
        * 1024
        * 1024
    )

    # --------------------------------------------------------
    # Small enough -> calculate SHA256
    # --------------------------------------------------------

    if stat.st_size <= hash_limit_bytes:

        sha256 = hashlib.sha256()

        with target.open("rb") as file:

            while True:

                chunk = file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                sha256.update(chunk)

        information["sha256"] = (
            sha256.hexdigest()
        )

    else:

        information["sha256"] = None

        information[
            "hash_skipped_reason"
        ] = (
            f"File larger than "
            f"{hash_limit_mb} MB"
        )

    return information


# ============================================================
# Run Recorder
# ============================================================

class RunRecorder:

    def __init__(
        self,
        request: str,
        model: str,
        system_prompt: str,
    ):

        # ----------------------------------------------------
        # Unique run identifier
        # ----------------------------------------------------

        self.run_id = (
            datetime.now()
            .astimezone()
            .strftime(
                "%Y%m%d_%H%M%S_%f"
            )
        )

        self.run_dir = (
            RUNS_ROOT / self.run_id
        )

        self.run_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        # ----------------------------------------------------
        # Initial state
        # ----------------------------------------------------

        self.tool_calls = []

        self.metadata = {
            "run_id": self.run_id,
            "status": "running",
            "start_time": current_time(),
            "end_time": None,

            "model": model,

            "environment": {
                "python": (
                    platform.python_version()
                ),
                "platform": (
                    platform.platform()
                ),
                "ollama_python": (
                    package_version("ollama")
                ),
                "xarray": (
                    package_version("xarray")
                ),
                "numpy": (
                    package_version("numpy")
                ),
                "netCDF4": (
                    package_version("netCDF4")
                ),
            },
        }

        # ----------------------------------------------------
        # Save original request and system prompt
        # ----------------------------------------------------

        (
            self.run_dir
            / "request.txt"
        ).write_text(
            request,
            encoding="utf-8",
        )

        (
            self.run_dir
            / "system_prompt.txt"
        ).write_text(
            system_prompt,
            encoding="utf-8",
        )

        write_json(
            self.run_dir
            / "run_metadata.json",
            self.metadata,
        )

        write_json(
            self.run_dir
            / "tool_calls.json",
            self.tool_calls,
        )

    # ========================================================
    # Tool record
    # ========================================================

    def record_tool(
        self,
        tool_name: str,
        arguments: dict,
        tool_result: str,
        validation_report=None,
    ):

        # ----------------------------------------------------
        # Parse validation report if available
        # ----------------------------------------------------

        validation = None

        if validation_report is not None:

            try:

                validation = json.loads(
                    validation_report
                )

            except Exception:

                validation = {
                    "status": "UNPARSEABLE",
                    "raw": str(
                        validation_report
                    ),
                }

        # ----------------------------------------------------
        # Input file provenance
        # ----------------------------------------------------

        input_file = None

        if "file_path" in arguments:

            input_file = (
                fingerprint_workspace_file(
                    arguments["file_path"]
                )
            )

        # ----------------------------------------------------
        # Record this tool execution
        # ----------------------------------------------------

        event = {
            "timestamp": current_time(),
            "tool_name": tool_name,
            "arguments": arguments,
            "input_file": input_file,
            "tool_result": tool_result,
            "validation": validation,
        }

        self.tool_calls.append(
            event
        )

        write_json(
            self.run_dir
            / "tool_calls.json",
            self.tool_calls,
        )

    # ========================================================
    # Final answer
    # ========================================================

    def record_final_answer(
        self,
        answer: str,
    ):

        (
            self.run_dir
            / "final_answer.md"
        ).write_text(
            answer,
            encoding="utf-8",
        )

    # ========================================================
    # Finish run
    # ========================================================

    def finish(
        self,
        status: str,
        error=None,
    ):

        self.metadata[
            "status"
        ] = status

        self.metadata[
            "end_time"
        ] = current_time()

        if error is not None:

            self.metadata[
                "error"
            ] = str(error)

        write_json(
            self.run_dir
            / "run_metadata.json",
            self.metadata,
        )