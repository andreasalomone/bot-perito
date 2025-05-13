import json
import logging
import pathlib
import re
from typing import Any
from uuid import uuid4

import jinja2
from openai import AsyncOpenAI
from openai import OpenAIError
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from app.core.config import settings

# Configure module logger
logger = logging.getLogger(__name__)


# Custom exceptions for better error handling
class LLMError(Exception):
    """Raised when LLM call fails"""


class JSONParsingError(Exception):
    """Raised when JSON parsing fails"""


# --- Reusable Jinja2 Environment ---
# Initialize Jinja2 environment for prompt templates
PROMPT_DIR = pathlib.Path(__file__).parent.parent / "services/prompt_templates"  # Adjusted path
try:
    loader = jinja2.FileSystemLoader(PROMPT_DIR)
    env = jinja2.Environment(loader=loader)
    logger.info("Jinja2 environment initialized successfully for path: %s", PROMPT_DIR)
except Exception:
    logger.exception("Failed to initialize Jinja2 environment at %s", PROMPT_DIR)
    # Depending on application needs, might re-raise or handle differently
    env = None  # Ensure env is defined, even if initialization fails


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
    retry=lambda exc: isinstance(exc, OpenAIError) and getattr(exc, "status", None) in {429, 500, 502, 503, 504},
)
async def call_llm(prompt: str) -> str:
    request_id = str(uuid4())
    logger.info("[%s] Making LLM API call with model: %s", request_id, settings.model_id)

    try:
        rsp = await client.chat.completions.create(
            model=settings.model_id,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )
        content = (rsp.choices[0].message.content or "").strip()
        logger.debug("[%s] LLM response received, length: %d chars", request_id, len(content))
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
    """Tenta di deserializzare `text` come JSON puro.
    Se fallisce, estrae il primo blocco { … } con regex e riprova.
    """
    request_id = str(uuid4())
    logger.debug("[%s] Attempting to parse JSON response, length: %d", request_id, len(text))

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[%s] Initial JSON parse failed, attempting regex extraction", request_id)
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
# Helper for executing LLM step with template rendering
# ---------------------------------------------------------------
async def execute_llm_step_with_template(
    request_id: str,
    step_name: str,
    template_name: str,
    context: dict[str, Any],
    expected_type: type = dict,  # Expect a dict by default
) -> Any:
    """Executes a single LLM step: load template, render, call LLM, parse JSON.
    Handles common LLM and JSON parsing errors, raising appropriate exceptions.
    """
    logger.debug("[%s] Executing LLM step: %s", request_id, step_name)
    if env is None:
        logger.error("[%s] Jinja2 environment not initialized for step %s", request_id, step_name)
        raise LLMError("Internal configuration error: Template environment not available.") from None

    try:
        template = env.get_template(template_name)
        prompt = template.render(**context)
        raw_response = await call_llm(prompt)
        data = extract_json(raw_response)

        # Optional: Validate the root type of the parsed JSON
        if not isinstance(data, expected_type):
            logger.error(
                "[%s] Invalid data type returned for step '%s'. Expected %s, got %s. Data: %s",
                request_id,
                step_name,
                expected_type.__name__,
                type(data).__name__,
                str(data)[:200],  # Log snippet of data
            )
            raise LLMError(f"Invalid data format received during '{step_name}' step.")

        logger.debug("[%s] Successfully executed LLM step: %s", request_id, step_name)
        return data

    except (LLMError, JSONParsingError) as e:
        # Errors from call_llm or extract_json or the type check above
        logger.error(
            "[%s] Failed LLM step '%s': %s",
            request_id,
            step_name,
            str(e),
            # exc_info=True is included in call_llm/extract_json if needed
        )
        # Re-raise directly as they are already specific
        raise e
    except jinja2.TemplateNotFound:
        logger.error(
            "[%s] Template not found: %s for step %s",
            request_id,
            template_name,
            step_name,
        )
        raise LLMError(f"Internal configuration error: Template '{template_name}' not found.") from None
    except Exception as e:
        logger.exception("[%s] Unexpected error in LLM step '%s'", request_id, step_name)
        raise LLMError(f"Unexpected error during '{step_name}' step.") from e


# ---------------------------------------------------------------
# Prompt builder (unchanged) - NOTE: This might also be refactored later
# ---------------------------------------------------------------

# Initialize Jinja2 environment
# PROMPT_DIR = pathlib.Path(__file__).parent / "prompt_templates" # Defined above
# loader = jinja2.FileSystemLoader(PROMPT_DIR) # Defined above
# env = jinja2.Environment(loader=loader) # Defined above


def build_prompt(
    template_excerpt: str,
    corpus: str,
    images: list[str],
    notes: str,
    reference_style_text: str,
) -> str:
    """Prompt per LLama4: restituisce SOLO un JSON con i campi del template.
    Il testo finale verrà inserito da docxtpl, quindi qui non serve
    formattazione.
    """
    if env is None:
        logger.error("Jinja2 environment not initialized for build_prompt")
        # Handle error appropriately - maybe return a default prompt or raise
        raise LLMError("Internal configuration error: Template environment not available.") from None

    # --- blocco stile aggiuntivo (facoltativo) -----------------------------
    extra_styles = ""
    if reference_style_text:
        extra_styles = (
            f"\\n\\nESEMPIO DI FORMATTAZIONE (SOLO PER TONO E STILE; IGNORA CONTENUTO):\\n<<<\\n{reference_style_text}\\n>>>"
        )

    # --- eventuali immagini -------------------------------------------------
    img_block = ""
    if images and settings.allow_vision:
        img_block = "\\n\\nFOTO_DANNI_BASE64:\\n" + "\\n".join(images)

    # --- carica e renderizza template Jinja2 ----------------------------------
    try:
        template = env.get_template("build_prompt.jinja2")
        prompt_content = template.render(
            template_excerpt=template_excerpt,
            extra_styles=extra_styles,
            corpus=corpus,
            notes=notes,
            img_block=img_block,
        )
        return prompt_content
    except jinja2.TemplateNotFound:
        logger.error("Template not found: build_prompt.jinja2")
        raise LLMError("Internal configuration error: Template 'build_prompt.jinja2' not found.") from None
    except Exception as e:
        logger.exception("Unexpected error building prompt")
        raise LLMError("Unexpected error building prompt.") from e
