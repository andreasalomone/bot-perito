import json
import io
import re
import logging
from uuid import uuid4
from docxtpl import DocxTemplate
from docx import Document

# Configure module logger
logger = logging.getLogger(__name__)


class DocBuilderError(Exception):
    """Base exception for document building errors"""


BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _add_markdown(par, txt):
    """Add markdown-style formatting to a paragraph."""
    try:
        pos = 0
        for m in BOLD_RE.finditer(txt):
            if m.start() > pos:
                par.add_run(txt[pos : m.start()])
            par.add_run(m.group(1)).bold = True
            pos = m.end()
        if pos < len(txt):
            par.add_run(txt[pos:])
    except Exception as e:
        logger.error("Failed to add markdown formatting: %s", str(e), exc_info=True)
        raise DocBuilderError("Failed to apply text formatting") from e


def inject(template_path: str, json_payload: str) -> bytes:
    """
    Inject JSON content into the document template.
    Returns the document as bytes.
    """
    request_id = str(uuid4())
    logger.info(
        "[%s] Starting document generation with template: %s", request_id, template_path
    )

    try:
        # Load template
        try:
            tpl = DocxTemplate(template_path)
            logger.debug("[%s] Successfully loaded template", request_id)
        except Exception as e:
            logger.error(
                "[%s] Failed to load template: %s", request_id, str(e), exc_info=True
            )
            raise DocBuilderError(f"Failed to load template: {template_path}") from e

        # Parse JSON
        try:
            ctx = json.loads(json_payload)
            logger.debug("[%s] Successfully parsed JSON payload", request_id)
        except json.JSONDecodeError as e:
            logger.error(
                "[%s] Invalid JSON payload: %s", request_id, str(e), exc_info=True
            )
            raise DocBuilderError("Invalid JSON payload") from e

        # ---------- 1 · mappa MAIUSC  ---------------------------------
        try:
            mapping = {
                "CLIENT": ctx["client"],
                "CLIENTADDRESS1": ctx["client_address1"],
                "CLIENTADDRESS2": ctx["client_address2"],
                "DATE": ctx["date"],
                "VSRIF": ctx["vs_rif"],
                "RIFBROKER": ctx["rif_broker"],
                "POLIZZA": ctx["polizza"],
                "NSRIF": ctx["ns_rif"],
                "ASSICURATO": ctx["assicurato"],
                "INDIRIZZOASSICURATO1": ctx["indirizzo_ass1"],
                "INDIRIZZOASSICURATO2": ctx["indirizzo_ass2"],
                "LUOGO": ctx["luogo"],
                "DATADANNO": ctx["data_danno"],
                "CAUSE": ctx["cause"],
                "DATAINCARICO": ctx["data_incarico"],
                "MERCE": ctx["merce"],
                "PESOMERCE": ctx["peso_merce"],
                "VALOREMERCE": ctx["valore_merce"],
                "DATAINTERVENTO": ctx["data_intervento"],
                "DINAMICA_EVENTI": "{{DINAMICA_EVENTI}}",
                "ACCERTAMENTI": "{{ACCERTAMENTI}}",
                "QUANTIFICAZIONE": "{{QUANTIFICAZIONE}}",
                "COMMENTO": "{{COMMENTO}}",
                "ALLEGATI": ctx["allegati"],
            }
            tpl.render(mapping)
            logger.debug("[%s] Successfully rendered template with mapping", request_id)
        except KeyError as e:
            logger.error(
                "[%s] Missing required field in JSON: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise DocBuilderError(f"Missing required field: {str(e)}") from e
        except Exception as e:
            logger.error(
                "[%s] Failed to render template: %s", request_id, str(e), exc_info=True
            )
            raise DocBuilderError("Failed to render template") from e

        # ---------- 2 · inserisci paragrafi nelle 3 sezioni ------------
        try:
            bio = io.BytesIO()
            tpl.save(bio)
            bio.seek(0)
            doc = Document(bio)

            section_map = {
                "{{DINAMICA_EVENTI}}": ctx["dinamica_eventi"],
                "{{ACCERTAMENTI}}": ctx["accertamenti"],
                "{{QUANTIFICAZIONE}}": ctx["quantificazione"],
                "{{COMMENTO}}": ctx["commento"],
            }

            for p in doc.paragraphs:
                for tag, content in section_map.items():
                    if tag in p.text:
                        style = p.style
                        p.clear()
                        paragraphs = [
                            t.strip() for t in content.split("\n\n") if t.strip()
                        ]
                        for idx, para in enumerate(paragraphs):
                            tgt = p if idx == 0 else doc.add_paragraph(style=style)
                            _add_markdown(tgt, para)
                        logger.debug("[%s] Processed section: %s", request_id, tag)
                        break

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
