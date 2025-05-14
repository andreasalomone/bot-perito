from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

# Import custom exceptions
from app.core.exceptions import PipelineError
from app.services.harmonization_service import HarmonizationService

# Assuming LLMError might still be caught in run, if not, remove.
from app.services.llm import LLMError

# Import the new step services
from app.services.outline_service import OutlineService
from app.services.section_expansion_service import SectionExpansionService

# Removed jinja2 import as template handling is in llm.py
# import jinja2


# Configure module logger
logger = logging.getLogger(__name__)

# Removed Jinja2 environment setup
# PROMPT_DIR = ...
# loader = ...
# env = ...


class PipelineService:
    """Orchestrates the report generation pipeline using dedicated step services."""

    def __init__(self):
        logger.info("Initializing PipelineService with step services")
        # Instantiate step services (can use DI later)
        self.outline_service = OutlineService()
        self.section_expansion_service = SectionExpansionService()
        self.harmonization_service = HarmonizationService()
        # self.chunk_model = embed # Keep if needed

    # Removed generate_outline method
    # Removed expand_section method
    # Removed harmonize method

    async def run(
        self,
        request_id: str,
        template_excerpt: str,
        corpus: str,
        notes: str,
        reference_style_text: str,
    ) -> AsyncGenerator[str, None]:
        """Run the report generation pipeline. (imgs parameter removed as unused)"""
        logger.info("[%s] Starting pipeline run with corpus length %d", request_id, len(corpus))
        try:
            yield json.dumps(
                {
                    "type": "status",
                    "message": "Initializing report generation...",
                }
            )

            # --- Input Validation ---
            if not template_excerpt:
                raise PipelineError("Input validation failed: Template excerpt is missing.")
            if not corpus:
                raise PipelineError("Input validation failed: Corpus is missing.")
            # NOTE: 'imgs' is currently unused by the core pipeline steps (outline, expand, harmonize)
            # but is kept for potential future use or compatibility with callers.

            yield json.dumps(
                {
                    "type": "status",
                    "message": "Generating report outline...",
                }
            )
            # 1. Outline - Use OutlineService
            outline = await self.outline_service.generate_outline(request_id, template_excerpt, corpus, notes)
            yield json.dumps(
                {
                    "type": "status",
                    "message": f"Outline generated with {len(outline)} sections.",
                }
            )

            # Context dictionary preparation is still useful here
            # for passing necessary data between steps if needed, but primarily for expansion

            yield json.dumps(
                {
                    "type": "status",
                    "message": "Expanding report sections...",
                }
            )
            # 3. Espandi sezioni - Use SectionExpansionService
            sections = {}
            for i, sec_outline_item in enumerate(outline):
                yield json.dumps(
                    {
                        "type": "status",
                        "message": f"Expanding section {i + 1}/{len(outline)}: {sec_outline_item['title']}...",
                    }
                )
                # Call the SectionExpansionService method
                text = await self.section_expansion_service.expand_section(
                    request_id,
                    sec_outline_item,
                    corpus,  # Pass corpus directly
                    template_excerpt,  # Pass template_excerpt directly
                    notes,  # Pass notes directly
                    reference_style_text,  # Pass styles directly
                )
                sections[sec_outline_item["section"]] = text
                yield json.dumps(
                    {
                        "type": "status",
                        "message": f"Section '{sec_outline_item['title']}' expanded.",
                    }
                )

            yield json.dumps(
                {
                    "type": "status",
                    "message": "Harmonizing report content...",
                }
            )
            # 4. Armonizza - Use HarmonizationService
            harmonized_sections_dict = await self.harmonization_service.harmonize(request_id, sections, reference_style_text)
            yield json.dumps(
                {
                    "type": "status",
                    "message": "Content harmonization complete.",
                }
            )

            logger.info("[%s] Pipeline completed successfully", request_id)

            # 5. Restituisci mappa per doc_builder
            yield json.dumps({"type": "data", "payload": harmonized_sections_dict})

        except PipelineError as e:
            error_message = f"Pipeline Error: {str(e)}"
            logger.error(
                "[%s] Pipeline run failed due to PipelineError: %s",
                request_id,
                str(e),
                exc_info=False,  # Keep false as lower layers should log details
            )
            yield json.dumps({"type": "error", "message": error_message})
        except LLMError as e:  # Catch LLMError explicitly if it can bubble up
            error_message = f"LLM Service Error: {str(e)}"
            logger.error(
                "[%s] Pipeline run failed due to LLMError: %s",
                request_id,
                str(e),
                exc_info=False,  # Keep false as lower layers should log details
            )
            yield json.dumps({"type": "error", "message": error_message})
        except Exception as e:
            error_message = f"An unexpected problem occurred in the pipeline: {str(e)}"
            logger.exception("[%s] Pipeline run failed with unexpected error", request_id)
            yield json.dumps(
                {
                    "type": "error",
                    "message": error_message,
                }
            )
        finally:
            # Ensure the 'finished' event is always sent
            logger.info("[%s] Pipeline processing finished.", request_id)
