import re

def summarize_text(text, style="Korte tekst"):
    sentences = re.split(r'[.!?]', text)
    short = " ".join(sentences[:5]).strip()

    actions = [s.strip() for s in sentences if re.search(r'\b(moet|zal|besluit|afspreken)\b', s, re.I)]

    if style == "Bulletpoints":
        summary = "\n".join([f"- {s.strip()}" for s in sentences[:5]])
    elif style == "Actiepunten":
        summary = "\n".join(actions) or "Geen specifieke actiepunten gevonden."
    else:
        summary = short

    return summary, actions
