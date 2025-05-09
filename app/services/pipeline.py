from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Dict, List
from uuid import uuid4

import jinja2

from app.services.llm import JSONParsingError, LLMError, call_llm, extract_json

# Configure module logger
logger = logging.getLogger(__name__)

# Initialize Jinja2 environment
PROMPT_DIR = pathlib.Path(__file__).parent / "prompt_templates"
loader = jinja2.FileSystemLoader(PROMPT_DIR)
env = jinja2.Environment(loader=loader)


class PipelineError(Exception):
    """Base exception for pipeline-related errors"""


class PipelineService:
    """Pipeline multi-step: outline → sezioni → armonizzazione."""

    def __init__(self):
        logger.info("Initializing PipelineService")
        # Funzione embed (Hugging Face API) per eventuale chunking locale
        # self.chunk_model = embed

    async def generate_outline(
        self,
        template_excerpt: str,
        corpus: str,
        similar_cases: List[Dict[str, Any]],
        notes: str,
        images: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Step 1: genera un outline JSON con titoli e bullet points per ciascuna sezione.
        Restituisce lista di titoli di sezione.
        """
        request_id = str(uuid4())
        logger.info(
            "[%s] Generating outline with %d similar cases and %d images",
            request_id,
            len(similar_cases),
            len(images),
        )

        try:
            # Define the separator for similar cases to avoid backslash in f-string expression
            similar_cases_separator = "\n\n---\n\n"
            similar_cases_str = (
                similar_cases_separator.join(
                    c["content_snippet"] for c in similar_cases
                )
                if similar_cases
                else ""
            )
            images_str = "; ".join(f"IMG{i + 1}" for i in range(len(images)))

            # Load and render prompt template
            template = env.get_template("generate_outline_prompt.jinja2")
            prompt = template.render(
                template_excerpt=template_excerpt,
                corpus=corpus,
                similar_cases_str=similar_cases_str,
                notes=notes,
                images_str=images_str,
            )
            raw = await call_llm(prompt)
            data = extract_json(raw)

            if not isinstance(data, list) or not data:
                logger.error(
                    "[%s] Invalid outline format returned from LLM", request_id
                )
                raise PipelineError("Invalid outline format")

            logger.info(
                "[%s] Successfully generated outline with %d sections",
                request_id,
                len(data),
            )
            return data

        except (LLMError, JSONParsingError) as e:
            logger.error(
                "[%s] Failed to generate outline: %s", request_id, str(e), exc_info=True
            )
            raise PipelineError("Failed to generate outline") from e
        except PipelineError:  # Specifically catch and re-raise PipelineErrors
            raise
        except Exception as e:
            logger.exception("[%s] Unexpected error in generate_outline", request_id)
            raise PipelineError("Unexpected error in outline generation") from e

    async def expand_section(
        self,
        section: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """
        Step 2: per ciascuna sezione, espandi con almeno 200 parole.
        context include template_excerpt, corpus, notes, images, similar_cases, e outline completo.
        """
        request_id = str(uuid4())
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
            current_extra_styles = context.get("extra_styles", "")
            # Define the separator for similar cases to avoid backslash in f-string expression
            similar_cases_separator = "\n\n---\n\n"
            similar_cases_str = similar_cases_separator.join(context.get("similar", []))

            section_questions = {
                "dinamica_eventi": "Chi, cosa, quando, dove e perché è avvenuto il sinistro?",
                "accertamenti": "Quali prove fotografiche e rilievi del danno sono stati eseguiti? Chi, dove e quando?",
                "quantificazione": "Dettaglia costi totali del danno come lista puntata o tabella testo.",
                "commento": "Fornisci una sintesi tecnica finale e le raccomandazioni.",
            }
            section_question = " e ".join(section_questions.get(sec_key, ""))

            # Load and render prompt template
            template = env.get_template("expand_section_prompt.jinja2")
            prompt = template.render(
                title=title,
                sec_key=sec_key,
                bullets=str(bullets),
                section_question=section_question,
                corpus=context["corpus"],
                template_excerpt=context["template_excerpt"],
                similar_cases_str=similar_cases_str,
                notes=context["notes"],
                current_extra_styles=current_extra_styles,
            )

            raw = await call_llm(prompt)
            out = extract_json(raw)
            content = out.get(sec_key, "")

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

        except (LLMError, JSONParsingError) as e:
            logger.error(
                "[%s] Failed to expand section '%s': %s",
                request_id,
                title,
                str(e),
                exc_info=True,
            )
            raise PipelineError(f"Failed to expand section {title}") from e
        except PipelineError:
            raise
        except Exception as e:
            logger.exception(
                "[%s] Unexpected error expanding section '%s'", request_id, title
            )
            raise PipelineError(f"Unexpected error expanding section {title}") from e

    async def harmonize(
        self, sections: Dict[str, str], extra_styles: str
    ) -> Dict[str, str]:
        """
        Step 3: unisci e uniforma lo stile.
        """
        request_id = str(uuid4())
        logger.info("[%s] Harmonizing %d sections", request_id, len(sections))

        try:
            # Define the joiner string separately to satisfy Black's AST parser
            section_joiner = "\\n\\n"
            sections_input_for_prompt = section_joiner.join(
                f'\\"{k}\\": \\"\\"\\"{json.dumps(v)[1:-1]}\\"\\"\\"'
                for k, v in sections.items()
            )

            # Load and render prompt template
            template = env.get_template("harmonize_prompt.jinja2")
            prompt = template.render(
                sections_input_for_prompt=sections_input_for_prompt,
                extra_styles_example=extra_styles,
            )

            raw_response = await call_llm(prompt)
            harmonized_data = extract_json(raw_response)

            if not isinstance(harmonized_data, dict) or not all(
                key in harmonized_data for key in sections.keys()
            ):
                logger.error(
                    "[%s] Invalid or incomplete harmonization result: %s",
                    request_id,
                    harmonized_data,
                )
                raise PipelineError(
                    "Harmonization returned invalid structure or missed sections."
                )

            logger.info(
                "[%s] Successfully harmonized sections. Keys: %s",
                request_id,
                list(harmonized_data.keys()),
            )
            return harmonized_data

        except (LLMError, JSONParsingError) as e:
            logger.error(
                "[%s] Failed to harmonize sections due to LLM/JSON error: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise PipelineError(f"Failed to harmonize sections: {str(e)}") from e
        except PipelineError:
            raise
        except Exception as e:
            logger.exception("[%s] Unexpected error in harmonization", request_id)
            raise PipelineError("Unexpected error in harmonization") from e

    async def run(
        self,
        template_excerpt: str,
        corpus: str,
        imgs: List[str],
        notes: str,
        similar: List[Dict[str, Any]],
        extra_styles: str,
    ) -> Dict[str, str]:
        request_id = str(uuid4())
        logger.info(
            "[%s] Starting pipeline run with corpus length %d", request_id, len(corpus)
        )

        try:
            # 1. Outline
            outline = await self.generate_outline(
                template_excerpt, corpus, similar, notes, imgs
            )

            # 2. Context dictionary
            context = {
                "corpus": corpus,
                "template_excerpt": template_excerpt,
                "similar": [case["content_snippet"] for case in similar],
                "notes": notes,
                "extra_styles": extra_styles,
            }

            # 3. Espandi sezioni
            sections = {}
            for sec_outline_item in outline:
                text = await self.expand_section(sec_outline_item, context)
                sections[sec_outline_item["section"]] = text

            # 4. Armonizza
            harmonized_sections_dict = await self.harmonize(sections, extra_styles)

            logger.info("[%s] Pipeline completed successfully", request_id)

            # 5. Restituisci mappa per doc_builder
            return harmonized_sections_dict

        except PipelineError:
            raise
        except Exception as e:
            logger.exception("[%s] Pipeline run failed", request_id)
            raise PipelineError("Pipeline execution failed") from e
