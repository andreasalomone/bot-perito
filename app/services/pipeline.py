from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import uuid4

from app.services.llm import JSONParsingError, LLMError, call_llm, extract_json

# Configure module logger
logger = logging.getLogger(__name__)


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

            # Prompt outline
            prompt = f"""
Usa il contesto qui sotto (estratti template, documenti, casi simili, note, immagini) per
generare un **outline dettagliato e completo** della perizia, in formato JSON:
[
  {{
    "section": "dinamica_eventi",
    "title": "Dinamica Evento",
    "bullets": ["punto 1", "punto 2", ...]
  }},
  {{
    "section": "accertamenti",
    "title": "Accertamenti Peritali",
    "bullets": ["punto 1", ...]
  }},
  {{
    "section": "quantificazione",
    "title": "Quantificazione Danno",
    "bullets": ["punto 1", ...]
  }},
  {{
    "section": "commento",
    "title": "Commento Finale",
    "bullets": ["punto 1", ...]
  }}
]

## TEMPLATE:
<<<
{template_excerpt}
>>>

## DOCUMENTI:
<<<
{corpus}
>>>

## CASI_SIMILI:
<<<
{similar_cases_separator.join(c["content_snippet"] for c in similar_cases) if similar_cases else ""}
>>>

## NOTE:
{notes}

## IMMAGINI (base64):
{" ; ".join(f"IMG{i + 1}" for i in range(len(images)))}

❗ Ogni sezione almeno 3 punti. Nessun testo al di fuori del JSON. No talk, just go.
"""
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

            prompt = f"""
Scrivi la sezione **{title}** (key="{sec_key}") della perizia, basandoti su:
- CONTEXTO perizio (template, documenti, casi simili, note)
- Outline bullets: {bullets}

Deve essere almeno 300 parole, rispondendo a tutte queste domande:
{" e ".join({
                "dinamica_eventi": "Chi, cosa, quando, dove e perché è avvenuto il sinistro?",
                "accertamenti": "Quali prove fotografiche e rilievi del danno sono stati eseguiti? Chi, dove e quando?",
                "quantificazione": "Dettaglia costi totali del danno come lista puntata o tabella testo.",
                "commento": "Fornisci una sintesi tecnica finale e le raccomandazioni."
            }.get(sec_key, ""))}

## CONTEXTO PERIZIALE (DOCUMENTI FORNITI):
<<<
{context["corpus"]}
>>>

## TEMPLATE EXCERPT (per struttura e terminologia generale):
<<<
{context["template_excerpt"]}
>>>

## CASI_SIMILI (per riferimento stilistico e informazioni specifiche se pertinenti):
<<<
{similar_cases_separator.join(context.get("similar", []))}
>>>

## NOTE AGGIUNTIVE FORNITE:
{context["notes"]}

## ESEMPIO DI STILE (USA QUESTO PER GUIDARE IL TONO, LA STRUTTURA DELLE FRASI E LA TERMINOLOGIA SPECIFICA):
<<<
{current_extra_styles}
>>>

❗ Restituisci JSON: {{ "{sec_key}": "<testo completo della sezione {title}>" }}
No talk, just go. Assicurati che il testo sia dettagliato e professionale, seguendo lo stile indicato.
"""
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
            escaped_double_quote = '\\"'  # This is the string: \"
            # Define the joiner string separately to satisfy Black's AST parser
            section_joiner = "\n\n"
            sections_input_for_prompt = section_joiner.join(
                f'"{k}": """{v.replace("\"", escaped_double_quote)}"""'
                for k, v in sections.items()
            )

            prompt = f"""
Data la seguente bozza di sezioni di una perizia e un esempio di stile, rivedi e armonizza ciascuna sezione per garantire coerenza di tono, stile, terminologia e fluidità. Correggi eventuali errori o ripetizioni.
Assicurati che ogni sezione mantenga il suo focus originale ma sia migliorata stilisticamente in base all'esempio fornito.

BOZZA SEZIONI DA ARMONIZZARE:
{{{{{sections_input_for_prompt}}}}}

ESEMPIO DI STILE DA APPLICARE (PER TONO, LUNGHEZZA FRASI, TERMINOLOGIA):
<<<
{extra_styles}
>>>

❗ Restituisci ESCLUSIVAMENTE un JSON valido contenente le versioni armonizzate di TUTTE le sezioni originali, usando le stesse chiavi.
Ad esempio:
{{
  "dinamica_eventi": "<testo armonizzato per dinamica_eventi>",
  "accertamenti": "<testo armonizzato per accertamenti>",
  "quantificazione": "<testo armonizzato per quantificazione>",
  "commento": "<testo armonizzato per commento>"
}}
Non aggiungere testo al di fuori del JSON.
"""
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
