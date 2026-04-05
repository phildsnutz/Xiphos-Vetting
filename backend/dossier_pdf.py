"""
Helios PDF brief wrapper.

The legacy PDF renderer has been retired. Production PDF generation now runs
through the Helios core brief engine so HTML and PDF artifacts share one
contract and one recommendation authority.
"""


def generate_pdf_dossier(vendor_id: str, user_id: str = "", hydrate_ai: bool = False) -> bytes:
    from helios_core.brief_engine import generate_pdf_brief

    return generate_pdf_brief(vendor_id, user_id=user_id, hydrate_ai=hydrate_ai)
