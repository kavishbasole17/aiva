"""Span-preserving text extraction and deterministic field detection.

Every extracted field carries page number, character offsets into the full
document text, the literal source quote, and the extractor that found it.
"""

import hashlib
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field

import pymupdf

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
LINKEDIN_RE = re.compile(r"linkedin\.com/in/[A-Za-z0-9_-]{3,}")
YEARS_RE = re.compile(
    r"(\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)",
    re.IGNORECASE,
)


@dataclass
class PageSpan:
    page_number: int
    start_offset: int
    end_offset: int


@dataclass
class DocumentText:
    full_text: str
    pages: list[PageSpan]
    content_hash: str

    def locate(self, start: int, end: int) -> tuple[int, int]:
        for page in self.pages:
            if page.start_offset <= start < page.end_offset:
                return page.page_number, start - page.start_offset
        return 0, start


@dataclass
class ExtractedField:
    field_name: str
    value: str
    confidence: float
    page_number: int
    start_offset: int
    end_offset: int
    source_quote: str
    extractor: str


@dataclass
class ExtractionResult:
    document: DocumentText
    fields: list[ExtractedField] = dataclass_field(default_factory=list)


def _pdf_pages(data: bytes) -> list[str]:
    # pymupdf's open()/Document are untyped upstream.
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        return [page.get_text() for page in doc]


def _docx_paragraphs(data: bytes) -> list[str]:
    import io

    import docx

    document = docx.Document(io.BytesIO(data))
    return ["\n".join(p.text for p in document.paragraphs)]


def _txt_text(data: bytes) -> list[str]:
    return [data.decode("utf-8", errors="replace")]


def load_document_text(filename: str, data: bytes) -> DocumentText:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        raw_pages = _pdf_pages(data)
    elif lower.endswith(".docx"):
        raw_pages = _docx_paragraphs(data)
    else:
        raw_pages = _txt_text(data)

    pages: list[PageSpan] = []
    chunks: list[str] = []
    offset = 0
    for index, text in enumerate(raw_pages):
        normalized = text.strip("\f")
        pages.append(
            PageSpan(
                page_number=index + 1, start_offset=offset, end_offset=offset + len(normalized)
            )
        )
        chunks.append(normalized)
        offset += len(normalized)
    full_text = "\n".join(chunks)
    return DocumentText(
        full_text=full_text,
        pages=pages,
        content_hash=hashlib.sha256(data).hexdigest(),
    )


def _regex_fields(document: DocumentText) -> list[ExtractedField]:
    results: list[ExtractedField] = []

    def add(field_name: str, match: re.Match[str], confidence: float) -> None:
        value = match.group(0).strip()
        page_number, page_offset = document.locate(match.start(), match.end())
        quote_start = max(0, match.start() - 40)
        quote_end = min(len(document.full_text), match.end() + 40)
        results.append(
            ExtractedField(
                field_name=field_name,
                value=value,
                confidence=confidence,
                page_number=page_number,
                start_offset=match.start(),
                end_offset=match.end(),
                source_quote=document.full_text[quote_start:quote_end].strip(),
                extractor="regex",
            )
        )

    seen: set[tuple[str, str]] = set()
    patterns = [
        ("email", EMAIL_RE, 0.99),
        ("linkedin", LINKEDIN_RE, 0.95),
        ("phone", PHONE_RE, 0.85),
    ]
    for name, pattern, confidence in patterns:
        for match in pattern.finditer(document.full_text):
            key = (name, match.group(0).strip())
            if key in seen:
                continue
            seen.add(key)
            add(name, match, confidence)
    return results


SKILLS_LEXICON: frozenset[str] = frozenset(
    {
        "python",
        "java",
        "typescript",
        "javascript",
        "go",
        "rust",
        "c++",
        "c#",
        "sql",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "kafka",
        "rabbitmq",
        "docker",
        "kubernetes",
        "terraform",
        "ansible",
        "aws",
        "azure",
        "gcp",
        "react",
        "vue",
        "angular",
        "node.js",
        "django",
        "fastapi",
        "flask",
        "spring",
        "graphql",
        "rest",
        "microservices",
        "ci/cd",
        "jenkins",
        "github actions",
        "gitlab",
        "linux",
        "bash",
        "pandas",
        "numpy",
        "tensorflow",
        "pytorch",
        "spark",
        "airflow",
        "dbt",
        "snowflake",
        "elasticsearch",
        "grafana",
        "prometheus",
        "jira",
    }
)

_SKILL_PATTERN = re.compile(
    r"|".join(re.escape(skill) for skill in sorted(SKILLS_LEXICON, key=len, reverse=True)),
    re.IGNORECASE,
)

YEARS_EXPERIENCE_MIN = 0.6


def extract_fields(document: DocumentText) -> list[ExtractedField]:
    fields = _regex_fields(document)
    seen_spans = {(f.field_name, f.start_offset) for f in fields}

    for match in _SKILL_PATTERN.finditer(document.full_text):
        key = ("skill", match.start())
        if key in seen_spans:
            continue
        seen_spans.add(key)
        value = match.group(0)
        page_number, _ = document.locate(match.start(), match.end())
        fields.append(
            ExtractedField(
                field_name="skill",
                value=value.lower(),
                confidence=0.9,
                page_number=page_number,
                start_offset=match.start(),
                end_offset=match.end(),
                source_quote=document.full_text[
                    max(0, match.start() - 40) : min(len(document.full_text), match.end() + 40)
                ].strip(),
                extractor="lexicon",
            )
        )

    years_matches = list(YEARS_RE.finditer(document.full_text))
    if years_matches:
        best = max(years_matches, key=lambda m: int(m.group(1)))
        page_number, _ = document.locate(best.start(), best.end())
        fields.append(
            ExtractedField(
                field_name="years_experience_claimed",
                value=best.group(1),
                confidence=0.7,
                page_number=page_number,
                start_offset=best.start(1),
                end_offset=best.end(1),
                source_quote=document.full_text[
                    max(0, best.start() - 40) : min(len(document.full_text), best.end() + 40)
                ].strip(),
                extractor="regex",
            )
        )

    first_line = next(
        (line.strip() for line in document.full_text.splitlines() if line.strip()), ""
    )
    if first_line and len(first_line.split()) <= 5 and all(w.isalpha() for w in first_line.split()):
        start = document.full_text.find(first_line)
        page_number, _ = document.locate(start, start + len(first_line))
        fields.append(
            ExtractedField(
                field_name="full_name",
                value=first_line,
                confidence=0.5,
                page_number=page_number,
                start_offset=start,
                end_offset=start + len(first_line),
                source_quote=first_line,
                extractor="heuristic",
            )
        )
    return fields
