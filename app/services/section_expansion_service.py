from __future__ import annotations

import logging
from typing import Any, Dict

from app.services.llm import JSONParsingError, LLMError, execute_llm_step_with_template

# Define PipelineError or import from a central location
from app.services.pipeline import PipelineError  # Example import

# class PipelineError(Exception):
#     """Base exception for pipeline-related errors (defined here for example)"""

logger = logging.getLogger(__name__)


class SectionExpansionService:
    async def expand_section(
        self,
        request_id: str,
        section: Dict[str, Any],
        corpus: str,
        template_excerpt: str,
        notes: str,
        current_extra_styles: str,
    ) -> str:
        """
        Expands a single section outline item into detailed content.
        """
        sec_key = section["section"]
        title = section["title"]
        bullets = section["bullets"]

        logger.info(
            "[%s] Expanding section '%s' with %d bullets",
            request_id,
            title,
            len(bullets),
        )

        try:
            section_questions = {
                "dinamica_eventi": "Chi, cosa, quando, dove e perché è avvenuto il sinistro?",
                "accertamenti": "Quali prove fotografiche e rilievi del danno sono stati eseguiti? Chi, dove e quando?",
                "quantificazione": "Dettaglia costi totali del danno come lista puntata o tabella testo.",
                "commento": "Fornisci una sintesi tecnica finale e le raccomandazioni.",
            }
            section_question = " e ".join(section_questions.get(sec_key, ""))

            # Prepare context for the helper method
            llm_context = {
                "title": title,
                "sec_key": sec_key,
                "bullets": str(bullets),
                "section_question": section_question,
                "corpus": corpus,
                "template_excerpt": template_excerpt,
                "notes": notes,
                "current_extra_styles": current_extra_styles,
            }

            # Use the helper function from llm module
            out = await execute_llm_step_with_template(
                request_id=request_id,
                step_name=f"expand_section ('{title}')",
                template_name="expand_section_prompt.jinja2",
                context=llm_context,
                expected_type=dict,  # Expecting a dict like {'section_key': 'content'}
            )

            content = out.get(sec_key, "")

            # Keep specific validation for section content
            if not content:
                logger.error(
                    "[%s] Empty content returned for section '%s'", request_id, title
                )
                raise PipelineError(f"Empty content for section {title}")

            logger.info(
                "[%s] Successfully expanded section '%s' to %d chars",
                request_id,
                title,
                len(content),
            )
            return content

        except (LLMError, JSONParsingError, PipelineError) as e:
            logger.error(
                "[%s] Expansion failed for section '%s': %s",
                request_id,
                title,
                str(e),
                exc_info=False,
            )
            raise PipelineError(f"Failed to expand section {title}: {str(e)}") from e
        except Exception as e:
            # Catch unexpected errors during this specific step's orchestration
            logger.exception(
                "[%s] Unexpected error expanding section '%s' orchestration",
                request_id,
                title,
            )
            raise PipelineError(f"Unexpected error expanding section {title}") from e
