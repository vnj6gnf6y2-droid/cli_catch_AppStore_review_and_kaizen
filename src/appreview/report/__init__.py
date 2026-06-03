"""appreview report package."""

from appreview.report.json_output import generate_json_report
from appreview.report.markdown import generate_markdown_report

__all__ = ["generate_json_report", "generate_markdown_report"]
