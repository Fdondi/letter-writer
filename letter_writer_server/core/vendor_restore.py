"""Merge a client vendor snapshot into session vendors without dropping letters."""

_VENDOR_TEXT_FIELDS = ("draft_letter", "final_letter", "letter_plan", "company_report")


def merge_restored_vendors(existing, incoming):
    """Merge incoming vendor fields into existing session vendors.

    An empty payload, or an empty object for one vendor, does not wipe letters
    already stored. Blank text fields are ignored so a partial client snapshot
    cannot erase a draft.
    """
    if not isinstance(incoming, dict) or not incoming:
        return existing if isinstance(existing, dict) else {}
    base = dict(existing) if isinstance(existing, dict) else {}
    for name, payload in incoming.items():
        if not isinstance(payload, dict) or not payload:
            continue
        current = base.get(name)
        if not isinstance(current, dict):
            base[name] = payload
            continue
        merged = dict(current)
        for key, value in payload.items():
            if value is None:
                continue
            if value == "" and key in _VENDOR_TEXT_FIELDS:
                continue
            merged[key] = value
        base[name] = merged
    return base
