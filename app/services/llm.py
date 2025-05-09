import json
import logging
import pathlib
import re
from uuid import uuid4

import jinja2
from openai import AsyncOpenAI, OpenAIError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.services.style_loader import load_style_samples

# Configure module logger
logger = logging.getLogger(__name__)

BULLET = "•"  # match bullet used in samples


# Custom exceptions for better error handling
class LLMError(Exception):
    """Raised when LLM call fails"""


class JSONParsingError(Exception):
    """Raised when JSON parsing fails"""


# ---------------------------------------------------------------
# OpenRouter client (sync) with required headers
# ---------------------------------------------------------------
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    default_headers={
        "HTTP-Referer": "http://localhost",
        "X-Title": "bot-perito",
        # Authorization is auto‑added from api_key
    },
)


# ---------------------------------------------------------------
# LLM call wrapped in a thread so FastAPI remains async
# ---------------------------------------------------------------
@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    retry=lambda exc: isinstance(exc, OpenAIError)
    and getattr(exc, "status", None) in {429, 500, 502, 503, 504},
)
async def call_llm(prompt: str) -> str:
    request_id = str(uuid4())
    logger.info(
        "[%s] Making LLM API call with model: %s", request_id, settings.model_id
    )

    try:
        rsp = await client.chat.completions.create(
            model=settings.model_id,
            messages=[
                {
                    "role": "system",
                    "content": "Rispondi SOLO con un JSON valido e nient'altro.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        content = (rsp.choices[0].message.content or "").strip()
        logger.debug(
            "[%s] LLM response received, length: %d chars", request_id, len(content)
        )
        return content
    except OpenAIError as e:
        logger.error("[%s] OpenAI API error: %s", request_id, str(e), exc_info=True)
        raise LLMError(f"OpenAI API error: {str(e)}") from e
    except Exception as e:
        logger.exception("[%s] Unexpected error in LLM call", request_id)
        raise LLMError(f"Unexpected error in LLM call: {str(e)}") from e


# ---------------------------------------------------------------
# JSON extractor helper
# ---------------------------------------------------------------
def extract_json(text: str) -> dict:
    """
    Tenta di deserializzare `text` come JSON puro.
    Se fallisce, estrae il primo blocco { … } con regex e riprova.
    """
    request_id = str(uuid4())
    logger.debug(
        "[%s] Attempting to parse JSON response, length: %d", request_id, len(text)
    )

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "[%s] Initial JSON parse failed, attempting regex extraction", request_id
        )
        try:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                logger.error("[%s] No JSON-like structure found in text", request_id)
                raise JSONParsingError("No JSON structure found in response")
            extracted = match.group(0)
            logger.info("[%s] Found JSON-like structure, attempting parse", request_id)
            return json.loads(extracted)
        except json.JSONDecodeError as e:
            logger.error(
                "[%s] Failed to parse extracted JSON: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise JSONParsingError(f"Failed to parse JSON: {str(e)}") from e
        except Exception as e:
            logger.exception("[%s] Unexpected error parsing JSON", request_id)
            raise JSONParsingError(f"Unexpected error parsing JSON: {str(e)}") from e


# ---------------------------------------------------------------
# Prompt builder (unchanged)
# ---------------------------------------------------------------

# Initialize Jinja2 environment
PROMPT_DIR = pathlib.Path(__file__).parent / "prompt_templates"
loader = jinja2.FileSystemLoader(PROMPT_DIR)
env = jinja2.Environment(loader=loader)


def build_prompt(
    template_excerpt: str,
    corpus: str,
    images: list[str],
    notes: str,
    similar_cases: list[dict] | None = None,
) -> str:
    """
    Prompt per LLama4: restituisce SOLO un JSON con i campi del template.
    Il testo finale verrà inserito da docxtpl, quindi qui non serve
    formattazione.
    """

    # --- blocco stile aggiuntivo (facoltativo) -----------------------------
    extra_styles_content = load_style_samples()
    extra_styles = ""
    if extra_styles_content:
        extra_styles = (
            "\n\nESEMPIO DI FORMATTAZIONE (SOLO PER TONO E STILE; IGNORA CONTENUTO):\n<<<\n"
            f"{extra_styles_content}\n>>>"
        )

    # --- eventuali immagini -------------------------------------------------
    img_block = ""
    if images and settings.allow_vision:
        img_block = "\n\nFOTO_DANNI_BASE64:\n" + "\n".join(images)

    # --- blocco casi simili ------------------------------------------------
    cases_block = ""
    if similar_cases:
        joined = "\n\n---\n\n".join(
            f"[{c['title']}]  \n{c['content_snippet']}" for c in similar_cases
        )
        cases_block = (
            "\n\nCASI_SIMILI (usa solo come riferimento stilistico e per informazioni quali indirizzi, cause):\n<<<\n"
            f"{joined}\n>>>"
        )

    # --- carica e renderizza template Jinja2 ----------------------------------
    template = env.get_template("build_prompt.jinja2")
    prompt_content = template.render(
        template_excerpt=template_excerpt,
        extra_styles=extra_styles,
        corpus=corpus,
        notes=notes,
        img_block=img_block,
        cases_block=cases_block,
    )

    return prompt_content
