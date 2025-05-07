from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import uuid4

from app.core.models import embedding_model
from app.services.llm import JSONParsingError, LLMError, call_llm, extract_json
from app.services.rag import RAGService

# Configure module logger
logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Base exception for pipeline-related errors"""


class PipelineService:
    """Pipeline multi-step: outline → sezioni → armonizzazione."""

    def __init__(self):
        logger.info("Initializing PipelineService")
        # RAG per contesto
        self.rag = RAGService()
        # Modello embedding per chunking se servisse
        try:
            self.chunk_model = embedding_model
            logger.debug("Initialized SentenceTransformer model")
        except Exception as e:
            logger.error(
                "Failed to initialize SentenceTransformer: %s", str(e), exc_info=True
            )
            raise PipelineError("Failed to initialize embedding model") from e

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
{"\n\n---\n\n".join(c["content_snippet"] for c in similar_cases)}
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
        sec = section["section"]
        title = section["title"]
        bullets = section["bullets"]

        logger.info(
            "[%s] Expanding section '%s' with %d bullets",
            request_id,
            title,
            len(bullets),
        )

        try:
            prompt = f"""
Scrivi la sezione **{title}** (key="{sec}") della perizia, basandoti su:
- CONTEXTO perizio (template, documenti, casi simili, note)
- Outline bullets: {bullets}

Deve essere almeno 300 parole, rispondendo a tutte queste domande:
{" e ".join({
                "dinamica_eventi": "Chi, cosa, quando, dove e perché è avvenuto il sinistro?",
                "accertamenti": "Quali prove fotografiche e rilievi del danno sono stati eseguiti? Chi, dove e quando?",
                "quantificazione": "Dettaglia costi totali del danno come lista puntata o tabella testo.",
                "commento": "Fornisci una sintesi tecnica finale e le raccomandazioni."
            }.get(sec, ""))}

## CONTEXTO:
<<<
{context["corpus"]}
>>>

## TEMPLATE EXCERPT:
<<<
{context["template_excerpt"]}
>>>

## CASI_SIMILI:
<<<
{"\n\n---\n\n".join(context["similar"])}
>>>

## NOTE:
{context["notes"]}

+❗ Restituisci JSON: {{ "{sec}": "<testo completo>" }}
"""
            raw = await call_llm(prompt)
            out = extract_json(raw)
            content = out.get(sec, "")

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
        except Exception as e:
            logger.exception(
                "[%s] Unexpected error expanding section '%s'", request_id, title
            )
            raise PipelineError(f"Unexpected error expanding section {title}") from e

    async def harmonize(self, sections: Dict[str, str]) -> str:
        """
        Step 3: unisci e uniforma lo stile.
        """
        request_id = str(uuid4())
        logger.info("[%s] Harmonizing %d sections", request_id, len(sections))

        try:
            prompt = f"""
Unisci le seguenti sezioni di perizia in un unico testo coeso,
uniforma tono e stile, correggi errori e ripetizioni:

<<<
{"".join(f"## {k}\n{v}\n\n" for k, v in sections.items())}
>>>

❗ Restituisci SOLO il TESTO finale, senza JSON né commenti. No talk, just go.
"""
            raw = await call_llm(prompt)
            result = raw.strip()

            if not result:
                logger.error("[%s] Empty result from harmonization", request_id)
                raise PipelineError("Empty harmonization result")

            logger.info(
                "[%s] Successfully harmonized text to %d chars", request_id, len(result)
            )
            return result

        except LLMError as e:
            logger.error(
                "[%s] Failed to harmonize sections: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise PipelineError("Failed to harmonize sections") from e
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
                "corpus": template_excerpt + "\n\n" + corpus,
                "template_excerpt": template_excerpt,
                "similar": similar,
                "notes": notes,
            }

            # 3. Espandi sezioni
            sections = {}
            for sec in outline:
                text = await self.expand_section(sec, context)
                sections[sec["section"]] = text

            # 4. Armonizza
            await self.harmonize(sections)

            logger.info("[%s] Pipeline completed successfully", request_id)

            # 5. Restituisci mappa per doc_builder
            return {
                "dinamica_eventi": sections.get("dinamica_eventi", ""),
                "accertamenti": sections.get("accertamenti", ""),
                "quantificazione": sections.get("quantificazione", ""),
                "commento": sections.get("commento", ""),
            }

        except Exception as e:
            logger.exception("[%s] Pipeline run failed", request_id)
            raise PipelineError("Pipeline execution failed") from e
