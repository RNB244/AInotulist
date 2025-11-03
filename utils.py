from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from datetime import datetime


def save_pdf(summary, actions):
    filename = f"samenvatting_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    c = canvas.Canvas(filename, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica", 12)
    c.drawString(50, height-50, f"Vergadersamenvatting - {datetime.now().strftime('%Y-%m-%d')}")
    y = height-80
    for line in summary.split("\n"):
        c.drawString(50, y, line)
        y -= 15
    if actions:
        y -= 20
        c.drawString(50, y, "Actiepunten:")
        for act in actions:
            y -= 15
            c.drawString(60, y, f"- {act}")
    c.save()
    return open(filename, "rb").read()
