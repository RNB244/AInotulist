import streamlit as st
# Gebruik altijd de audio_recorder_streamlit component (handmatig start/stop)
HAVE_RECORDER = False
RECORDER_KIND = None  # 'ars'
try:
    from audio_recorder_streamlit import audio_recorder  # handmatige start/stop door mic opnieuw te klikken
    HAVE_RECORDER = True
    RECORDER_KIND = 'ars'
except Exception:
    HAVE_RECORDER = False
    RECORDER_KIND = None
import whisper
from summarize import summarize_text
from utils import save_pdf
from datetime import datetime
import os
import os
import tempfile
import sys
import shutil
import traceback
import subprocess

# Helper voor bestandsnamen
def get_filename(base, ext, title=None):
    date = datetime.now().strftime('%Y%m%d_%H%M%S')
    if title:
        safe_title = "_".join(title.split())
        return f"{base}_{safe_title}_{date}.{ext}"
    return f"{base}_{date}.{ext}"

st.set_page_config(page_title="AI Vergader Samenvatter", layout="centered")

st.title("🎧 AI Vergader Samenvatter")
st.markdown("Neem op of upload audio → krijg transcript + samenvatting.")

# Whisper modelkeuze (Cloud-vriendelijk standaard 'base') en caching
@st.cache_resource(show_spinner=False)
def get_whisper_model(name: str):
    # Forceer CPU in de cloud en voorkom half-precision issues
    return whisper.load_model(name, device="cpu")

with st.sidebar:
    model_size = st.selectbox(
        "Whisper model",
        ["tiny", "base", "small"],
        index=0,
        help="Kleinere modellen zijn sneller/goedkoper op de cloud."
    )

# Meeting-titel invoer
meeting_title = st.text_input("Meeting titel (optioneel)", "")

st.markdown("---")
# Als recorder niet beschikbaar is, standaard op "Uploaden" zetten
mode = st.radio("📤 Kies invoer", ["🎙️ Opnemen", "📁 Uploaden"], index=(1 if not HAVE_RECORDER else 0))
if not HAVE_RECORDER:
    st.info("Opnemen-module niet gevonden. Uploaden is wel beschikbaar. (Installeer optioneel 'audio-recorder-streamlit' of 'streamlit-audiorec')")

audio_bytes = None
if mode == "🎙️ Opnemen":
    if not HAVE_RECORDER:
        st.warning("Opnemen is niet beschikbaar (module kon niet geladen worden). Kies \"Uploaden\".")
    else:
        try:
            # audio-recorder-streamlit: klik om te starten, klik opnieuw om te stoppen
            st.caption("Klik op de microfoon om te starten, klik opnieuw om te stoppen. De opname stopt NIET automatisch bij stilte.")
            audio_bytes = audio_recorder(
                text="Start/stop opname",
                sample_rate=16000,
            )
        except Exception:
            st.warning("Audio opnemen niet beschikbaar. Gebruik upload.")
elif mode == "📁 Uploaden":
    uploaded = st.file_uploader("Upload MP3 of WAV", type=["mp3", "wav"])
    if uploaded:
        audio_bytes = uploaded.read()

if audio_bytes:
    st.info("Bezig met transcriberen... ⏳")
    # Schrijf naar tijdelijk bestand zodat ffmpeg/whisper het kan lezen
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        # Laad (of hergebruik) model
        model = get_whisper_model(model_size)
        with st.spinner("Transcriptie in uitvoering…"):
            # fp16=False i.v.m. CPU; temperature=0 voor deterministischer output
            result = model.transcribe(tmp_path, language="nl", fp16=False, temperature=0)
        transcript = result.get("text", "")
    except Exception as e:
        st.error("Er ging iets mis tijdens de transcriptie.")
        # Bewaar laatste exception voor diagnosepaneel
        st.session_state["last_error"] = traceback.format_exc()
        st.exception(e)
        transcript = ""
    finally:
        # Opruimen van temp bestand
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    if transcript:
        st.success("✅ Transcriptie voltooid")
    st.subheader("📝 Transcriptie")

    # Zoekfunctie in transcriptie
    search_query = st.text_input("🔍 Zoek in transcriptie", "")
    if search_query:
        found = [line for line in transcript.splitlines() if search_query.lower() in line.lower()]
        st.text_area("Resultaten", "\n".join(found) if found else "Geen resultaten.", height=150)
    st.text_area("Volledige transcriptie", transcript, height=250)

    # Downloadbare transcriptie
    transcript_filename = get_filename("transcript", "txt", meeting_title)
    st.download_button("⬇️ Download transcriptie", transcript.encode(), file_name=transcript_filename)

    st.subheader("⚙️ Kies samenvattingsstijl")
    style = st.selectbox(
        label="Kies samenvattingsstijl",
        options=["Korte tekst", "Bulletpoints", "Actiepunten"],
        label_visibility="collapsed",
    )

    summary, actions = summarize_text(transcript, style)

    st.subheader("📋 Samenvatting")
    st.write(summary)
    if actions:
        st.markdown("### ✅ Actiepunten")
        for a in actions:
            st.markdown(f"- {a}")

    # Downloadbare actiepunten
    if actions:
        actions_filename = get_filename("actiepunten", "txt", meeting_title)
        st.download_button("⬇️ Download actiepunten", "\n".join(actions).encode(), file_name=actions_filename)

    pdf_file = save_pdf(summary, actions)
    pdf_filename = get_filename("samenvatting", "pdf", meeting_title)
    st.download_button("⬇️ Download PDF", pdf_file, file_name=pdf_filename)

    # Save summary PDF locally (non-persistent op Cloud, maar handig lokaal)
    try:
        summaries_dir = "summaries"
        if not os.path.exists(summaries_dir):
            os.makedirs(summaries_dir)
        with open(os.path.join(summaries_dir, pdf_filename), "wb") as f:
            f.write(pdf_file)
    except Exception:
        # Geen fatale fout als we niet kunnen schrijven
        pass

st.markdown("""
<style>
textarea {font-size:18px !important;}
button, .stButton>button {font-size:18px !important; padding:16px 32px; border-radius:12px;}
.stTextInput>div>input {font-size:20px !important; padding:12px;}
.stDownloadButton>button {font-size:18px !important; padding:16px 32px; border-radius:12px;}
</style>
""", unsafe_allow_html=True)

# Diagnostiek-paneel voor snelle probleemoplossing
with st.expander("🔎 Diagnostiek"):
    try:
        import torch
        device = "cuda" if getattr(torch, "cuda", None) and torch.cuda.is_available() else "cpu"
        st.write({
            "python": sys.version.split(" ")[0],
            "whisper_version": getattr(whisper, "__version__", "unknown"),
            "torch_version": getattr(torch, "__version__", "not installed"),
            "device": device,
            "ffmpeg_path": shutil.which("ffmpeg"),
            "model_selected": model_size,
        })
    except Exception:
        st.write("Kon diagnose-info niet ophalen.")
    # Laat laatste fout zien indien aanwezig
    if "last_error" in st.session_state:
        st.code(st.session_state["last_error"], language="text")
