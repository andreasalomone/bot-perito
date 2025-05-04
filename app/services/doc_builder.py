import json
import io
from docxtpl import DocxTemplate

def inject(template_path: str, json_payload: str) -> bytes:
    tpl = DocxTemplate(template_path)
    ctx = json.loads(json_payload)
    tpl.render({
        "CLIENT": ctx["client"],
        "CLIENTADDRESS1": ctx["client_address1"],
        "CLIENTADDRESS2": ctx["client_address2"],
        "DATE": ctx["date"],
        "VSRIF": ctx["vs_rif"],
        "RIFBROKER": ctx["rif_broker"],
        "POLIZZA": ctx["polizza"],
        "NSRIF": ctx["ns_rif"],
        "SUBJECT": ctx["subject"],
        "BODY": ctx["body"],
    })
    bio = io.BytesIO(); tpl.save(bio); bio.seek(0)
    return bio.read()
