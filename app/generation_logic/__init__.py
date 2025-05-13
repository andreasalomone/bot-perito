"""Generation logic package.

This package groups the helper functions that orchestrate the multi-step document generation
workflow (file extraction, context preparation, report pipeline, etc.).
Keeping them here allows `app/api/routes.py` to stay minimal and focused on
HTTP routing while core business logic lives in composable modules.
"""

from .clarification_flow import build_report_with_clarifications  # noqa: F401
from .context_preparation import _extract_base_context  # noqa: F401
from .context_preparation import _load_template_excerpt  # noqa: F401

# Re-export most commonly-used helpers for convenience
from .file_processing import _validate_and_extract_files  # noqa: F401
from .report_finalization import _generate_and_stream_docx  # noqa: F401
from .stream_orchestrator import _stream_report_generation_logic  # noqa: F401
