import os
import sqlite3
from pathlib import Path

# Restrict checkpoint deserialization behavior.
os.environ.setdefault(
    "LANGGRAPH_STRICT_MSGPACK",
    "true",
)

from langgraph.checkpoint.sqlite import SqliteSaver


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
)

CHECKPOINT_DB = (
    PROJECT_ROOT
    / "checkpoints.sqlite"
)


def create_checkpointer():
    """
    Create a persistent SQLite LangGraph checkpointer.
    """

    connection = sqlite3.connect(
        CHECKPOINT_DB,
        check_same_thread=False,
    )

    checkpointer = SqliteSaver(
        connection
    )

    return (
        connection,
        checkpointer,
    )