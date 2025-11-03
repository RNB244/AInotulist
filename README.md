# Meeting Summarizer (NL)

Streamlit-app om vergaderingen op te nemen of te uploaden, te transcriberen (Whisper) en samen te vatten met actiepunten. Ontworpen voor mobiel gebruik en export (PDF/TXT).

## Features
- Opnemen of uploaden (fallback recorder aanwezig)
- Whisper-transcriptie (NL)
- Samenvattingsstijlen + automatische actiepunten
- Zoeken in transcript
- Download: transcript & actiepunten (TXT) en PDF
- Mobielvriendelijke UI

## Vereisten
- Python 3.10 (aanbevolen op Windows i.v.m. Torch/Whisper)
- Visual C++ Redistributable (x64) voor Torch DLLs (Windows)

## Installatie en run (lokaal)
1. Maak (optioneel) een virtualenv en activeer die.
2. Installeer afhankelijkheden:
   ```bash
   pip install -r requirements.txt
   ```
3. Start de app:
   ```bash
   python -m streamlit run meeting-summarizer/app.py
   ```

## Deploy naar Streamlit Cloud
- Main file path: `meeting-summarizer/app.py`
- Repo: deze map als GitHub repo (public/private)
- Let op: Whisper/Torch kan zwaar zijn. Alternatieven:
  - `faster-whisper` (CPU-vriendelijker)
  - OpenAI Whisper API gebruiken i.p.v. lokaal model

## Structuur
```
meeting-summarizer/
  app.py
  summarize.py
  utils.py
  requirements.txt
  summaries/
```

## Licentie
MIT
