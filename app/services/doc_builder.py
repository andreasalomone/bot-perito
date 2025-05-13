import io

# import json # No longer needed for json.loads
import logging
import re
from uuid import uuid4

from docx import Document
from docxtpl import DocxTemplate

from app.models.report_models import (  # Keep for potential future use or type hinting if context becomes more specific
    ReportContext,
)

# Configure module logger
logger = logging.getLogger(__name__)


class DocBuilderError(Exception):
    """Base exception for document building errors"""


BOLD_RE = re.compile(r"\\*\\*(.+?)\\*\\*")

# Maps the DOCX template tags (keys) to the expected keys in the context dictionary (values).
TEMPLATE_TAG_TO_CONTEXT_KEY_MAPPING: dict[str, str] = {
    "CLIENT": "client",
    "CLIENTADDRESS1": "client_address1",
    "CLIENTADDRESS2": "client_address2",
    "DATE": "date",
    "VSRIF": "vs_rif",
    "RIFBROKER": "rif_broker",
    "POLIZZA": "polizza",
    "NSRIF": "ns_rif",
    "ASSICURATO": "assicurato",
    "INDIRIZZOASSICURATO1": "indirizzo_ass1",
    "INDIRIZZOASSICURATO2": "indirizzo_ass2",
    "LUOGO": "luogo",
    "DATADANNO": "data_danno",
    "CAUSE": "cause",
    "DATAINCARICO": "data_incarico",
    "MERCE": "merce",
    "PESOMERCE": "peso_merce",
    "VALOREMERCE": "valore_merce",
    "DATAINTERVENTO": "data_intervento",
    "ALLEGATI": "allegati",
    # Tags that will be replaced by multi-paragraph content later
    "DINAMICA_EVENTI": "{{DINAMICA_EVENTI}}",
    "ACCERTAMENTI": "{{ACCERTAMENTI}}",
    "QUANTIFICAZIONE": "{{QUANTIFICAZIONE}}",
    "COMMENTO": "{{COMMENTO}}",
}

# Maps the section placeholder tags found in the template (keys)
# to the expected keys in the context dictionary that hold their content (values).
SECTION_PLACEHOLDER_TO_CONTEXT_KEY_MAPPING: dict[str, str] = {
    "{{DINAMICA_EVENTI}}": "dinamica_eventi",
    "{{ACCERTAMENTI}}": "accertamenti",
    "{{QUANTIFICAZIONE}}": "quantificazione",
    "{{COMMENTO}}": "commento",
}


def _add_markdown(par, txt: str):  # Added type hint for txt
    """Add markdown-style formatting to a paragraph."""
    # Ensure txt is a string before processing
    processed_txt = txt if isinstance(txt, str) else ""
    try:
        pos = 0
        for m in BOLD_RE.finditer(processed_txt):
            if m.start() > pos:
                par.add_run(processed_txt[pos : m.start()])
            par.add_run(m.group(1)).bold = True
            pos = m.end()
        if pos < len(processed_txt):
            par.add_run(processed_txt[pos:])
    except Exception as e:
        logger.error("Failed to add markdown formatting: %s", str(e), exc_info=True)
        raise DocBuilderError("Failed to apply text formatting") from e


def inject(template_path: str, context: ReportContext) -> bytes:
    """Inject ReportContext content into the document template.
    Returns the document as bytes.
    """
    request_id = str(uuid4())
    logger.info("[%s] Starting document generation with template: %s", request_id, template_path)

    try:
        # Load template
        try:
            tpl = DocxTemplate(template_path)
            logger.debug("[%s] Successfully loaded template", request_id)
        except Exception as e:
            logger.error("[%s] Failed to load template: %s", request_id, str(e), exc_info=True)
            raise DocBuilderError(f"Failed to load template: {template_path}") from e

        # JSON parsing is no longer needed here, context is already a dict
        # try:
        #     ctx = json.loads(json_payload) # Removed
        #     logger.debug("[%s] Successfully parsed JSON payload", request_id)
        # except json.JSONDecodeError as e:
        #     logger.error(
        #         "[%s] Invalid JSON payload: %s", request_id, str(e), exc_info=True
        #     )
        #     raise DocBuilderError("Invalid JSON payload") from e

        # Use the passed 'context' dictionary directly (formerly 'ctx')

        # ---------- 1 · mappa MAIUSC  ---------------------------------
        try:
            # Prepare mapping_data for DocxTemplate.render()
            # Use getattr(context, key, default_value) for safer access.
            # Defaulting to an empty string if attribute is missing or None.
            mapping_data = {
                tpl_tag: getattr(context, ctx_key, None)  # Let DocxTemplate handle None
                for tpl_tag, ctx_key in TEMPLATE_TAG_TO_CONTEXT_KEY_MAPPING.items()
                # Exclude section keys handled later if they are in this map
                if ctx_key not in SECTION_PLACEHOLDER_TO_CONTEXT_KEY_MAPPING.values()
            }
            # Special handling for 'allegati' if it's a list, convert to string
            allegati_content = getattr(context, "allegati", [])  # Default to empty list if missing
            if isinstance(allegati_content, list):
                # Ensure items are strings before joining
                mapping_data["ALLEGATI"] = "\\n".join(str(item) for item in allegati_content if item is not None)
            elif allegati_content is not None:
                mapping_data["ALLEGATI"] = str(allegati_content)
            else:
                mapping_data["ALLEGATI"] = ""  # Ensure it's an empty string if None

            # Add placeholders for sections to be filled later
            for _tag, _key in SECTION_PLACEHOLDER_TO_CONTEXT_KEY_MAPPING.items():
                mapping_data[_tag.removeprefix("{{").removesuffix("}}")] = _tag  # e.g., DINAMICA_EVENTI: "{{DINAMICA_EVENTI}}"

            tpl.render(mapping_data)
            logger.debug("[%s] Successfully rendered template with mapping_data", request_id)
        except AttributeError as e:
            logger.error(
                "[%s] Missing expected attribute in ReportContext for template rendering: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise DocBuilderError(f"Missing required field in context: {str(e)}") from e
        except Exception as e:
            logger.error(
                "[%s] Failed to render template with initial mapping: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise DocBuilderError("Failed to render template with initial mapping") from e

        # ---------- 2 · inserisci paragrafi nelle sezioni ------------
        try:
            bio = io.BytesIO()
            tpl.save(bio)
            bio.seek(0)
            doc = Document(bio)

            # Prepare section_content from context using attribute access
            section_content_map = {
                placeholder: getattr(context, ctx_key, "")  # Default to empty string
                for placeholder, ctx_key in SECTION_PLACEHOLDER_TO_CONTEXT_KEY_MAPPING.items()
            }

            for p in doc.paragraphs:
                current_text = p.text
                for (
                    tag,
                    _content_key_in_map,
                ) in SECTION_PLACEHOLDER_TO_CONTEXT_KEY_MAPPING.items():
                    # Check if the exact placeholder tag exists in the paragraph text
                    if tag in current_text:
                        # Retrieve the actual content string using the placeholder tag
                        content_string = section_content_map.get(tag, "")
                        style = p.style
                        # Clear the placeholder paragraph content.
                        # Need to be careful if other text exists in the same paragraph.
                        # Assuming the placeholder is the only content for simplicity based on prior structure.
                        # If not, more complex replacement logic is needed.
                        p.clear()

                        # Ensure content_string is a string before splitting
                        paragraphs_to_insert = [
                            t.strip()
                            for t in (str(content_string) if content_string is not None else "").split("\\n\\n")
                            if t.strip()
                        ]

                        if not paragraphs_to_insert:
                            # If content is empty after splitting, add an empty run to keep paragraph
                            p.add_run("")
                        else:
                            for idx, para_text in enumerate(paragraphs_to_insert):
                                target_par = p if idx == 0 else doc.add_paragraph(style=style)
                                if idx > 0:  # Clear potentially duplicated content if using add_paragraph
                                    target_par.clear()
                                _add_markdown(target_par, para_text)
                        logger.debug(
                            "[%s] Processed section for placeholder: %s",
                            request_id,
                            tag,
                        )
                        break  # Move to the next paragraph in doc.paragraphs

            out = io.BytesIO()
            doc.save(out)
            out.seek(0)
            result = out.read()

            logger.info(
                "[%s] Successfully generated document, size: %d bytes",
                request_id,
                len(result),
            )
            return result

        except Exception as e:
            logger.error(
                "[%s] Failed to process document sections: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise DocBuilderError("Failed to process document sections") from e

    except DocBuilderError:
        raise
    except Exception as e:
        logger.exception("[%s] Unexpected error in document generation", request_id)
        raise DocBuilderError("Unexpected error in document generation") from e
