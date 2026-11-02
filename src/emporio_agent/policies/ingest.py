"""Turn the policy PDF into one chunk per numbered (sub)section.

Chunking by the manual's own structure keeps each rule together with its heading,
so retrieved text is self-contained and citable ("section 4.1").
"""
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

HEADING = re.compile(r"^(\d{1,2}(?:\.\d)?)\.?\s+([A-ZÀ-Ú].{1,80})$")
NOISE = re.compile(r"^(Empório da Música\s+Manual de Políticas e Procedimentos|Página \d+)$")


@dataclass(frozen=True)
class Chunk:
    section: str
    title: str
    text: str

    @property
    def content(self) -> str:
        return f"[Seção {self.section}] {self.title}\n{self.text}"


def _extract_lines(pdf_path: Path) -> list[str]:
    reader = PdfReader(str(pdf_path))
    lines: list[str] = []
    for page in reader.pages[1:]:  # page 1 is the cover; contact data is added below
        for raw in page.extract_text(extraction_mode="layout").splitlines():
            line = re.sub(r"\s{2,}", " | ", raw.strip()) if "   " in raw.strip() else raw.strip()
            line = line.replace("• | ", "• ")
            if line and not NOISE.match(line):
                lines.append(line)
    return lines


def _cover_chunk(pdf_path: Path) -> Chunk:
    text = PdfReader(str(pdf_path)).pages[0].extract_text(extraction_mode="layout")
    text = "\n".join(re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip())
    return Chunk("capa", "Contatos da loja (capa do manual)", text)


def load_chunks(pdf_path: Path) -> list[Chunk]:
    chunks: list[Chunk] = [_cover_chunk(pdf_path)]
    parents: dict[str, str] = {}
    current: tuple[str, str] | None = None
    body: list[str] = []

    def flush():
        if current and "\n".join(body).strip():
            section, title = current
            top = section.split(".")[0]
            full_title = title if "." not in section else f"{parents.get(top, '')} > {title}"
            chunks.append(Chunk(section, full_title, "\n".join(body).strip()))

    for line in _extract_lines(pdf_path):
        m = HEADING.match(line)
        if m:
            flush()
            body = []
            section, title = m.group(1), m.group(2).strip()
            if "." not in section:
                parents[section] = title
            current = (section, title)
        elif current:
            body.append(line)
    flush()
    return chunks
