from __future__ import annotations
import os, asyncio
from typing import Any, Dict, List
from supabase import create_client
from async_lru import alru_cache
from sentence_transformers import SentenceTransformer

from app.services.rag import RAGService
from app.services.llm import call_llm, extract_json
from app.core.config import settings

class PipelineService:
    """Pipeline multi-step: outline → sezioni → armonizzazione."""

    def __init__(self):
        # RAG per contesto
        self.rag = RAGService()
        # Modello embedding per chunking se servisse
        self.chunk_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

    async def generate_outline(
        self,
        template_excerpt: str,
        corpus: str,
        similar_cases: List[Dict[str, Any]],
        notes: str,
        images: List[str],
    ) -> List[str]:
        """
        Step 1: genera un outline JSON con titoli e bullet points per ciascuna sezione.
        Restituisce lista di titoli di sezione.
        """
        # Prompt outline
        prompt = f"""
Usa il contesto qui sotto (estratti template, documenti, casi simili, note, immagini) per
generare un **outline dettagliato** della perizia, in formato JSON:
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
{" ; ".join(f"IMG{i+1}" for i in range(len(images)))}

❗ Ogni sezione almeno 3 punti. Nessun testo al di fuori del JSON.
"""
        raw = await call_llm(prompt)
        data = extract_json(raw)
        return data   # list of dicts

    async def expand_section(
        self,
        section: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """
        Step 2: per ciascuna sezione, espandi con almeno 300 parole.
        context include template_excerpt, corpus, notes, images, similar_cases, e outline completo.
        """
        sec = section["section"]
        title = section["title"]
        bullets = section["bullets"]
        # costruisci prompt
        prompt = f"""
Scrivi la sezione **{title}** (key="{sec}") della perizia, basandoti su:
- CONTEXTO perizio (template, documenti, casi simili, note)
- Outline bullets: {bullets}

Deve essere almeno 300 parole, rispondendo a tutte queste domande:
{" e ".join({
    '"dinamica_eventi": "Chi, cosa, quando, dove, perché?"',
    '"accertamenti": "Quali prove fotografiche e rilievi?"',
    '"quantificazione": "Dettaglia costi come lista puntata o tabella testo."',
    '"commento": "Sintesi tecnica finale e raccomandazioni."'
}.get(section["section"], ""))}

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

❗ Restituisci JSON: {{ "{section['section']}": "<testo completo>" }}
"""
        raw = await call_llm(prompt)
        out = extract_json(raw)
        return out.get(sec, "")

    async def harmonize(
        self,
        sections: Dict[str, str]
    ) -> str:
        """
        Step 3: unisci e uniforma lo stile.
        """
        prompt = f"""
Unisci le seguenti sezioni di perizia in un unico testo coeso,
uniforma tono e stile, correggi errori e ripetizioni:

<<<
{"".join(f"## {k}\n{v}\n\n" for k,v in sections.items())}
>>>

❗ Restituisci SOLO il TESTO finale, senza JSON né commenti.
"""
        raw = await call_llm(prompt)
        return raw.strip()

    async def run(self,
                  template_excerpt: str,
                  corpus: str,
                  imgs: List[str],
                  notes: str,
                  similar: List[Dict[str,Any]]
    ) -> Dict[str,str]:
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
        final_text = await self.harmonize(sections)
        # 5. Restituisci mappa per doc_builder
        return {
            "dinamica_eventi": sections.get("dinamica_eventi",""),
            "accertamenti":    sections.get("accertamenti",""),
            "quantificazione": sections.get("quantificazione",""),
            "commento":        sections.get("commento",""),
        }
