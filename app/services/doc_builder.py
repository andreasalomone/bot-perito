import json, io, re
from docxtpl import DocxTemplate
from docx import Document

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

def _add_markdown(par, txt):
    pos = 0
    for m in BOLD_RE.finditer(txt):
        if m.start() > pos:
            par.add_run(txt[pos:m.start()])
        par.add_run(m.group(1)).bold = True
        pos = m.end()
    if pos < len(txt):
        par.add_run(txt[pos:])

def inject(template_path: str, json_payload: str) -> bytes:
    tpl = DocxTemplate(template_path)
    ctx = json.loads(json_payload)

    # ---------- 1 · mappa MAIUSC  ---------------------------------
    mapping = {
        "CLIENT":            ctx["client"],
        "CLIENTADDRESS1":    ctx["client_address1"],
        "CLIENTADDRESS2":    ctx["client_address2"],
        "DATE":              ctx["date"],
        "VSRIF":             ctx["vs_rif"],
        "RIFBROKER":         ctx["rif_broker"],
        "POLIZZA":           ctx["polizza"],
        "NSRIF":             ctx["ns_rif"],
        "ASSICURATO":        ctx["assicurato"],
        "INDIRIZZOASSICURATO1": ctx["indirizzo_ass1"],
        "INDIRIZZOASSICURATO2": ctx["indirizzo_ass2"],
        "LUOGO":             ctx["luogo"],
        "DATADANNO":         ctx["data_danno"],
        "CAUSE":             ctx["cause"],
        "DATAINCARICO":      ctx["data_incarico"],
        "MERCE":             ctx["merce"],
        "PESOMERCE":         ctx["peso_merce"],
        "VALOREMERCE":       ctx["valore_merce"],
        "DATAINTERVENTO":    ctx["data_intervento"],
        "DINAMICA_EVENTI":   "{{DINAMICA_EVENTI}}",
        "ACCERTAMENTI"       "{{ACCERTAMENTI}}"
        "QUANTIFICAZIONE":   "{{QUANTIFICAZIONE}}",
        "COMMENTO":          "{{COMMENTO}}",
        "ALLEGATI":          ctx["allegati"],
    }
    tpl.render(mapping)

    # ---------- 2 · inserisci paragrafi nelle 3 sezioni ------------
    bio = io.BytesIO(); tpl.save(bio); bio.seek(0)
    doc = Document(bio)

    section_map = {
        "{{DINAMICA_EVENTI}}":        ctx["dinamica_eventi"],
        "{{ACCERTAMENTI}}":           ctx["accertamenti"],
        "{{QUANTIFICAZIONE}}":        ctx["quantificazione"],
        "{{COMMENTO}}":               ctx["commento"],
    }

    for p in doc.paragraphs:
        for tag, content in section_map.items():
            if tag in p.text:
                style = p.style
                p.clear()
                for idx, para in enumerate([t.strip() for t in content.split("\n\n") if t.strip()]):
                    tgt = p if idx == 0 else doc.add_paragraph(style=style)
                    _add_markdown(tgt, para)
                break

    out = io.BytesIO(); doc.save(out); out.seek(0)
    return out.read()