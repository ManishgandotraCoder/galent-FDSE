"""Read a PDF text layer or OCR a photograph.

Digital PDFs use the embedded text. Photographs go through macOS Vision when
it is available, then Tesseract. The matcher never sees the raw page.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
OCR_SOURCE = BACKEND_ROOT / "scripts" / "macos_ocr.swift"
OCR_BINARY = BACKEND_ROOT / ".cache" / "macos_ocr"
OCR_CACHE = BACKEND_ROOT / ".cache" / "ocr-v3"


@dataclass
class OcrToken:
    """One word or line from OCR, with a box in Vision's bottom-left coordinates."""

    text: str
    confidence: float
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def mid_y(self) -> float:
        return (self.ymin + self.ymax) / 2

    @property
    def center_x(self) -> float:
        return (self.xmin + self.xmax) / 2


@dataclass
class ReadText:
    text: str
    source: str
    ocr_confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    tokens: list[OcrToken] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)


def read_bytes(data: bytes, name: str) -> ReadText:
    suffix = Path(name).suffix.lower()
    if data.startswith(b"%PDF") or suffix == ".pdf":
        try:
            pages = [_clean(page) for page in _pdf_pages(data)]
        except Exception as exc:  # noqa: BLE001 - surface a readable extraction warning
            return ReadText(text="", source="pdf", warnings=[f"Could not read the PDF text layer ({exc})."])
        pages = [page for page in pages if page.strip()]
        if not pages:
            return ReadText(text="", source="pdf", warnings=["The PDF has no text layer."])
        return ReadText(text="\n".join(pages), source="pdf", pages=pages if len(pages) > 1 else [])

    if _looks_like_image(data, suffix):
        return _ocr(data, suffix or ".img")

    if suffix in {".txt", ".csv"} or not suffix:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return ReadText(text="", source="unknown", warnings=["This file is not a PDF, image, or UTF-8 text document."])
        return ReadText(text=_clean(text), source="text")

    return ReadText(
        text="",
        source="unknown",
        warnings=["This file type has no reader. Upload a PDF or an image."],
    )


# PDFium keeps process-wide state. Intake reads several files at once.
_pdf_lock = threading.Lock()


def _pdf_pages(data: bytes) -> list[str]:
    import pypdfium2 as pdfium

    with _pdf_lock:
        return _pdf_pages_locked(pdfium, data)


def _pdf_pages_locked(pdfium, data: bytes) -> list[str]:
    pdf = pdfium.PdfDocument(data)
    pages: list[str] = []
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            text_page = page.get_textpage()
            try:
                pages.append(text_page.get_text_bounded() or "")
            finally:
                text_page.close()
                page.close()
    finally:
        pdf.close()
    return pages


def _looks_like_image(data: bytes, suffix: str) -> bool:
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}:
        return True
    return data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG") or data.startswith(b"GIF8")


def _ocr(data: bytes, suffix: str) -> ReadText:
    warnings: list[str] = []
    binary = _vision_binary()
    if binary is not None:
        cached = _cached_vision(data)
        if cached is not None:
            text, confidence, tokens = cached
            return ReadText(
                text=_clean(text),
                source="ocr",
                ocr_confidence=confidence,
                warnings=warnings,
                tokens=tokens,
            )
        text, confidence, tokens, error = _run_vision(binary, data, suffix)
        if error is None and text.strip():
            return ReadText(
                text=_clean(text),
                source="ocr",
                ocr_confidence=confidence,
                warnings=warnings,
                tokens=tokens,
            )
        if error:
            warnings.append(error)

    tesseract = shutil.which("tesseract")
    if tesseract:
        text, confidence, error = _run_tesseract([tesseract, "--psm", "6", "-l", "eng+hin"], data, suffix)
        if error is None and text.strip():
            return ReadText(text=_clean(text), source="ocr", ocr_confidence=confidence, warnings=warnings)
        if error:
            warnings.append(error)

    if not warnings:
        warnings.append("No OCR engine is available. Install the macOS Vision helper or Tesseract.")
    return ReadText(text="", source="ocr", warnings=warnings)


def _vision_binary() -> Path | None:
    if (
        OCR_BINARY.exists()
        and OCR_SOURCE.exists()
        and OCR_BINARY.stat().st_mtime >= OCR_SOURCE.stat().st_mtime
    ):
        return OCR_BINARY
    if not OCR_SOURCE.exists() or shutil.which("swiftc") is None:
        return None
    OCR_BINARY.parent.mkdir(parents=True, exist_ok=True)
    compiled = subprocess.run(
        ["swiftc", "-O", str(OCR_SOURCE), "-o", str(OCR_BINARY)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if compiled.returncode != 0 or not OCR_BINARY.exists():
        return None
    return OCR_BINARY


def _cached_vision(data: bytes) -> tuple[str, float | None, list[OcrToken]] | None:
    path = OCR_CACHE / f"{hashlib.sha256(data).hexdigest()}.txt"
    if not path.is_file():
        return None
    return _vision_stdout(path.read_text(encoding="utf-8"))


def _run_vision(
    binary: Path,
    data: bytes,
    suffix: str,
) -> tuple[str, float | None, list[OcrToken], str | None]:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        path = handle.name
    try:
        completed = subprocess.run(
            [str(binary), path],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or "OCR failed").strip().splitlines()
            return "", None, [], detail[-1] if detail else "OCR failed"
        text, confidence, tokens = _vision_stdout(completed.stdout)
        if tokens:
            OCR_CACHE.mkdir(parents=True, exist_ok=True)
            destination = OCR_CACHE / f"{hashlib.sha256(data).hexdigest()}.txt"
            destination.write_text(completed.stdout, encoding="utf-8")
        return text, confidence, tokens, None
    except subprocess.TimeoutExpired:
        return "", None, [], "OCR timed out."
    finally:
        Path(path).unlink(missing_ok=True)


def _vision_stdout(stdout: str) -> tuple[str, float | None, list[OcrToken]]:
    tokens: list[OcrToken] = []
    for raw in stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) < 6:
            continue
        try:
            confidence = float(parts[0])
            xmin, ymin, xmax, ymax = (float(part) for part in parts[1:5])
        except ValueError:
            continue
        text = parts[5].strip()
        if not text:
            continue
        tokens.append(OcrToken(text=text, confidence=confidence, xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax))
    ordered = sorted(tokens, key=lambda token: (-token.mid_y, token.xmin))
    scores = [token.confidence for token in tokens]
    confidence = sum(scores) / len(scores) if scores else None
    return "\n".join(token.text for token in ordered), confidence, tokens


def _run_tesseract(command: list[str], data: bytes, suffix: str) -> tuple[str, float | None, str | None]:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        path = handle.name
    try:
        completed = subprocess.run(
            [*command, path, "stdout"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or "tesseract failed").strip().splitlines()
            return "", None, detail[-1] if detail else "tesseract failed"
        return completed.stdout, None, None
    except subprocess.TimeoutExpired:
        return "", None, "OCR timed out."
    finally:
        Path(path).unlink(missing_ok=True)


def _clean(text: str) -> str:
    cleaned = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.strip() for line in cleaned.split("\n"))
