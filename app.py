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
from io import BytesIO
from typing import Optional
try:
    from pydub import AudioSegment, effects
    HAVE_PYDUB = True
except Exception:
    HAVE_PYDUB = False

# Audio splitter helper
def split_audio_bytes(audio_bytes, chunk_minutes=10):
    """
    Split audio bytes (mp3/wav/m4a) into chunks of chunk_minutes (default 10 min).
    Returns list of AudioSegment objects.
    """
    if not HAVE_PYDUB:
        return [audio_bytes]
    seg = AudioSegment.from_file(BytesIO(audio_bytes))
    chunk_ms = chunk_minutes * 60 * 1000
    chunks = []
    for start in range(0, len(seg), chunk_ms):
        end = min(start + chunk_ms, len(seg))
        chunks.append(seg[start:end])
    return chunks

# Helper: export a chunk (AudioSegment or bytes) to a wav file path
def export_chunk_to_wav(chunk, tmp_path: str, cleanup: bool):
    """
    Export one chunk to wav at tmp_path.
    - If chunk is an AudioSegment: optional cleanup, then export.
    - If chunk is bytes: write raw bytes; ffmpeg will decode by content.
    """
    # If we have an AudioSegment
    if HAVE_PYDUB and 'AudioSegment' in globals() and isinstance(chunk, AudioSegment):
        seg = chunk
        if cleanup:
            seg = seg.set_channels(1).set_frame_rate(16000)
            seg = effects.normalize(seg)
            seg = seg.high_pass_filter(100)
        seg.export(tmp_path, format="wav")
        return
    # Fallback: chunk as bytes
    if isinstance(chunk, (bytes, bytearray)):
        with open(tmp_path, "wb") as f:
            f.write(chunk)
        return
    # Last resort: raise to be caught by caller
    raise TypeError("Unsupported chunk type for export")

# Vragenlijst helpers
from questionnaire import load_questions_from_docx, assign_segments_to_questions, flatten_mapping_to_text
from utils_questionnaire import build_docx_with_notes

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
        ["tiny", "base", "small", "medium"],
        index=2,
        help="Grotere modellen zijn nauwkeuriger maar trager."
    )
    cleanup_audio = st.checkbox(
        "Audio optimaliseren (normaliseren + high-pass)",
        value=True,
        help=("Verbetert verstaanbaarheid bij zachte opnames. Vereist pydub/ffmpeg." 
              + (" (pydub beschikbaar)" if HAVE_PYDUB else " (pydub niet beschikbaar)") )
    )
    custom_prompt = st.text_input(
        "Voorkeurtermen/namen (optioneel)",
        placeholder="Bijv. namen, vakjargon, bedrijfsnamen",
        help="Wordt als hint meegegeven aan Whisper voor betere herkenning."
    )

    st.markdown("---")
    st.header("🧩 Vragenlijst")
    uploaded_docx = st.file_uploader("Upload je standaard vragenlijst (.docx)", type=["docx"])
    questions = []
    if uploaded_docx:
        try:
            questions = load_questions_from_docx(uploaded_docx)
            st.success(f"{len(questions)} vragen geladen uit je .docx")
            with st.expander("Voorbeeld van ingelezen vragen"):
                for i, q in enumerate(questions[:10], start=1):
                    st.markdown(f"**{i}.** {q}")
                if len(questions) > 10:
                    st.caption(f"... en {len(questions)-10} meer")
        except Exception as e:
            st.error(f"Kon vragenlijst niet inlezen: {e}")
    auto_assign = st.checkbox("Automatisch toewijzen aan vragen", value=True)
    threshold = st.slider("Match drempel (hoger = strenger)", 40, 90, 55, step=1)

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
    uploaded = st.file_uploader("Upload MP3, WAV of M4A", type=["mp3", "wav", "m4a"])
    if uploaded:
        audio_bytes = uploaded.read()


if audio_bytes:
    st.info("Bezig met transcriberen... ⏳")
    transcript = ""
    segments = []
    chunk_minutes = 10
    audio_chunks = split_audio_bytes(audio_bytes, chunk_minutes=chunk_minutes)
    all_transcripts = []
    all_segments = []
    model = get_whisper_model(model_size)
    for i, chunk in enumerate(audio_chunks):
        st.info(f"Transcriberen deel {i+1} van {len(audio_chunks)}...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp_path = tmp.name
        try:
            export_chunk_to_wav(chunk, tmp_path, cleanup=cleanup_audio)
            transcribe_kwargs = dict(
                language="nl",
                fp16=False,
                temperature=0,
                beam_size=5,
                condition_on_previous_text=False,
            )
            if custom_prompt:
                transcribe_kwargs["initial_prompt"] = custom_prompt
            result = model.transcribe(tmp_path, **transcribe_kwargs)
            all_transcripts.append(result.get("text", ""))
            all_segments.extend(result.get("segments", []) or [])
        except Exception as e:
            st.error(f"Fout bij deel {i+1}: {e}")
            st.session_state["last_error"] = traceback.format_exc()
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    transcript = "\n".join(all_transcripts)
    segments = all_segments

    if transcript:
        st.success("✅ Transcriptie voltooid")
    st.subheader("📝 Transcriptie")

    search_query = st.text_input("🔍 Zoek in transcriptie", "")
    if search_query:
        found = [line for line in transcript.splitlines() if search_query.lower() in line.lower()]
        st.text_area("Resultaten", "\n".join(found) if found else "Geen resultaten.", height=150)
    st.text_area("Volledige transcriptie", transcript, height=250)

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

    if actions:
        actions_filename = get_filename("actiepunten", "txt", meeting_title)
        st.download_button("⬇️ Download actiepunten", "\n".join(actions).encode(), file_name=actions_filename)

    pdf_file = save_pdf(summary, actions)
    pdf_filename = get_filename("samenvatting", "pdf", meeting_title)
    st.download_button("⬇️ Download PDF", pdf_file, file_name=pdf_filename)

    try:
        summaries_dir = "summaries"
        if not os.path.exists(summaries_dir):
            os.makedirs(summaries_dir)
        with open(os.path.join(summaries_dir, pdf_filename), "wb") as f:
            f.write(pdf_file)
    except Exception:
        pass

    # ====== Per-vraag notulen ======
    if transcript and questions:
        st.subheader("🧠 Notulen per vraag")
        notes_per_question = {}
        actions_per_question = {}
        debug = []
        if auto_assign and segments:
            mapping, debug = assign_segments_to_questions(segments, questions, threshold=threshold, sequential=True)
            merged = flatten_mapping_to_text(mapping)
            for idx in range(len(questions)):
                text_for_q = merged.get(idx, "").strip()
                if not text_for_q:
                    notes_per_question[idx] = []
                    actions_per_question[idx] = []
                    continue
                q_summary, q_actions = summarize_text(text_for_q, "Bulletpoints")
                bullets = [ln.strip("- ").strip() for ln in q_summary.splitlines() if ln.strip()]
                notes_per_question[idx] = bullets
                actions_per_question[idx] = q_actions or []
        else:
            st.info("Automatische toewijzing uitgeschakeld of geen segmenten beschikbaar.")

        for i, q in enumerate(questions):
            with st.expander(f"Vraag {i+1}: {q}"):
                bullets = notes_per_question.get(i, [])
                if bullets:
                    for b in bullets:
                        st.markdown(f"- {b}")
                else:
                    st.caption("Geen notulen aan deze vraag gekoppeld.")
                acts = actions_per_question.get(i, [])
                if acts:
                    st.markdown("**Actiepunten:**")
                    for a in acts:
                        st.markdown(f"- {a}")

        col1, col2 = st.columns(2)
        with col1:
            if summary:
                st.download_button("⬇️ Download PDF (globaal)", data=pdf_file, file_name=pdf_filename)
        with col2:
            docx_bytes = build_docx_with_notes(
                title=f"Notulen projectevaluatie – {datetime.now().strftime('%Y-%m-%d')}",
                questions=questions,
                notes_per_question=notes_per_question,
                actions_per_question=actions_per_question,
                global_summary=summary,
                global_actions=actions
            )
            st.download_button("⬇️ Download Word (alles)", data=docx_bytes, file_name=f"notulen_{datetime.now().strftime('%Y-%m-%d')}.docx")

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
