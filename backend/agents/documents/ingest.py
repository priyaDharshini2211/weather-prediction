"""Text extraction (PDF / TXT) and section-aware chunking for retrieval."""
import io
import re
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PyPdfError

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150


class DocumentIngestError(Exception):
    pass


@dataclass
class Chunk:
    index: int
    page: int | None
    text: str
    heading: str = ""


def extract_text(data: bytes, file_type: str) -> list[tuple[int | None, str]]:
    """Returns [(page_number | None, text)]."""
    if file_type == "txt":
        for encoding in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                return [(None, data.decode(encoding))]
            except UnicodeDecodeError:
                continue
        raise DocumentIngestError("Could not decode the text file.")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentIngestError("Password-protected PDFs are not supported.")
        pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    except DocumentIngestError:
        raise
    except (PyPdfError, ValueError, OSError, KeyError) as error:
        raise DocumentIngestError("Could not read this PDF. It may be corrupted.") from error

    if not any(text.strip() for _, text in pages):
        raise DocumentIngestError("No selectable text found in this PDF (it may be a scanned image).")
    return pages


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


KNOWN_HEADINGS = frozenset(
    {
        "summary", "profile", "objective", "career objective", "professional summary", "about me",
        "skills", "technical skills", "key skills", "core competencies",
        "education", "academic background", "qualifications",
        "experience", "work experience", "professional experience", "employment", "internships",
        "projects", "academic projects", "personal projects",
        "certifications", "courses", "training", "achievements", "awards", "publications",
        "languages", "interests", "hobbies", "volunteering", "contact", "references",
    }
)


def _heading_of(line: str) -> str | None:
    """A short standalone line is a section heading if it is a known one ("Skills") or ALL CAPS ("WORK HISTORY")."""
    stripped = line.strip()
    candidate = stripped.rstrip(":").strip()
    if not 2 <= len(candidate) <= 40 or stripped.endswith((".", ",", ";")):
        return None
    if candidate.lower() in KNOWN_HEADINGS or (candidate.isupper() and len(candidate.split()) <= 4):
        return candidate.title()
    return None


def _split_long(unit: str) -> list[str]:
    """Break one over-long line/paragraph at sentence boundaries, then at spaces."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", unit):
        while len(sentence) > CHUNK_SIZE:
            cut = sentence.rfind(" ", 0, CHUNK_SIZE)
            cut = cut if cut > 0 else CHUNK_SIZE
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + len(sentence) + 1 > CHUNK_SIZE:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _pack(units: list[str]) -> list[str]:
    """Greedily pack lines into <= CHUNK_SIZE bodies; the last line of a full body is repeated as overlap when it is short."""
    bodies, current = [], []
    for unit in units:
        size = sum(len(u) + 1 for u in current)
        if current and size + len(unit) > CHUNK_SIZE:
            bodies.append("\n".join(current))
            current = [current[-1]] if len(current[-1]) <= CHUNK_OVERLAP else []
        current.append(unit)
    if current:
        bodies.append("\n".join(current))
    return bodies


def split_into_chunks(pages: list[tuple[int | None, str]]) -> list[Chunk]:
    """Section-aware chunks (~CHUNK_SIZE chars). Every chunk starts with its section heading so it is
    understandable - and embeddable - on its own ("Skills\\nPython, Django ..."). Remembers the page."""
    chunks: list[Chunk] = []
    heading = ""
    for page, raw in pages:
        sections: list[tuple[str, list[str]]] = [(heading, [])]
        for line in _normalise(raw).split("\n"):
            if not line.strip():
                continue
            found = _heading_of(line)
            if found:
                heading = found
                sections.append((heading, []))
            else:
                units = _split_long(line.strip()) if len(line) > CHUNK_SIZE else [line.strip()]
                sections[-1][1].extend(units)
        for section_heading, units in sections:
            for body in _pack(units):
                text = f"{section_heading}\n{body}" if section_heading else body
                chunks.append(Chunk(len(chunks), page, text, section_heading))
    return chunks
