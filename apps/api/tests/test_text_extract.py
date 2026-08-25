import io

import pymupdf
import pytest

from app.text_extract import extract_fields, load_document_text

RESUME_TEXT = """Jane Doe
jane.doe@example.test | linkedin.com/in/janedoe | +1 (415) 555-0100
Senior backend engineer with 7 years of experience building distributed systems.
Skills: Python, PostgreSQL, Docker, Kubernetes, Kafka
"""


def _pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=10)
    return doc.tobytes()


def _docx_bytes(text: str) -> bytes:
    import docx

    document = docx.Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _fields_by_name(fields: list) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for extracted in fields:
        grouped.setdefault(extracted.field_name, []).append(extracted)
    return grouped


@pytest.mark.parametrize(
    "suffix,data_builder",
    [("pdf", _pdf_bytes), ("docx", _docx_bytes), ("txt", lambda t: t.encode())],
)
def test_extraction_finds_core_fields_with_valid_spans(suffix: str, data_builder) -> None:
    document = load_document_text(f"resume.{suffix}", data_builder(RESUME_TEXT))
    assert document.content_hash
    grouped = _fields_by_name(extract_fields(document))

    assert grouped["email"][0].value == "jane.doe@example.test"
    assert grouped["email"][0].confidence >= 0.95
    assert "linkedin.com/in/janedoe" in grouped["linkedin"][0].value
    phone_values = [f.value for f in grouped.get("phone", [])]
    assert any("415" in value for value in phone_values)

    skills = {f.value for f in grouped.get("skill", [])}
    assert {"python", "postgresql", "docker", "kubernetes", "kafka"} <= skills

    years = grouped["years_experience_claimed"]
    assert years[0].value == "7"
    name = grouped["full_name"]
    assert name[0].value == "Jane Doe"


def test_every_field_span_resolves_to_its_value() -> None:
    document = load_document_text("resume.txt", RESUME_TEXT.encode())
    fields = extract_fields(document)
    assert fields
    for field in fields:
        slice_value = document.full_text[field.start_offset : field.end_offset]
        assert slice_value.lower() == field.value.lower(), f"{field.field_name}: bad span"
        quote = field.source_quote
        assert field.value.lower() in quote.lower()


def test_pdf_pages_map_correctly() -> None:
    doc = pymupdf.open()
    first = doc.new_page()
    first.insert_text((72, 72), RESUME_TEXT, fontsize=10)
    second = doc.new_page()
    second.insert_text((72, 72), "Page two content with python mention.", fontsize=10)
    data = doc.tobytes()

    document = load_document_text("resume.pdf", data)
    assert len(document.pages) == 2
    fields = extract_fields(document)
    python_fields = [f for f in fields if f.value == "python"]
    assert len(python_fields) == 2
    pages_of_python = {f.page_number for f in python_fields}
    assert pages_of_python == {1, 2}


def test_deterministic_content_hash() -> None:
    a = load_document_text("resume.txt", RESUME_TEXT.encode())
    b = load_document_text("resume.txt", RESUME_TEXT.encode())
    assert a.content_hash == b.content_hash


def test_corrupt_pdf_raises() -> None:
    with pytest.raises(RuntimeError):
        load_document_text("broken.pdf", b"%PDF-1.4 garbage")
