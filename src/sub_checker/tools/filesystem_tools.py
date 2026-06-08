"""Tools for agents to check filesystem (figures, etc.)."""

from __future__ import annotations

from sub_checker.models import Manuscript


def list_figures(manuscript: Manuscript) -> str:
    """List all files in the figures directory."""
    if not manuscript.figure_dir or not manuscript.figure_dir.exists():
        return "No figures directory found."
    files = sorted(manuscript.figure_dir.iterdir())
    if not files:
        return "Figures directory is empty."
    return "Files in figures directory:\n" + "\n".join(f"  - {f.name}" for f in files)


def check_file_exists(manuscript: Manuscript, filename: str) -> str:
    """Check if a file exists in the figures directory."""
    if not manuscript.figure_dir:
        return f"No figures directory configured. Cannot check for '{filename}'."
    path = manuscript.figure_dir / filename
    if path.exists():
        size = path.stat().st_size
        return f"File '{filename}' exists ({size} bytes)."
    # Try case-insensitive match
    for f in manuscript.figure_dir.iterdir():
        if f.name.lower() == filename.lower():
            return f"File '{filename}' not found, but '{f.name}' exists (case mismatch)."
    return f"File '{filename}' does NOT exist in {manuscript.figure_dir}."


TOOL_LIST_FIGURES = {
    "name": "list_figures",
    "description": "List all files in the manuscript's figures directory.",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

TOOL_CHECK_FILE_EXISTS = {
    "name": "check_file_exists",
    "description": "Check if a specific file exists in the figures directory.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename to check (e.g. 'Figure1.png')",
            }
        },
        "required": ["filename"],
    },
}
