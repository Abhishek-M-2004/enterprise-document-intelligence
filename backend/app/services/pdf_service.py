"""PDF validation and text extraction service using PyMuPDF."""

from dataclasses import dataclass
import io
from pathlib import Path
from typing import List, Tuple, Union
import pymupdf

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

PDF_MAGIC_BYTES = b"%PDF-"


class PDFProcessingError(Exception):
    """Raised when PDF extraction or validation fails."""
    pass


@dataclass
class ExtractedPage:
    """Represents text extracted from a single PDF page."""
    page_number: int  # 1-indexed
    text: str
    char_count: int


@dataclass
class ExtractedDocument:
    """Aggregated extraction results from an entire document."""
    page_count: int
    pages: List[ExtractedPage]
    total_characters: int

    @property
    def is_empty(self) -> bool:
        """Returns True if no printable text was extracted from any page."""
        return self.total_characters == 0 or all(not p.text.strip() for p in self.pages)


class PDFService:
    """Encapsulates validation and PyMuPDF text extraction operations."""

    @staticmethod
    def validate_pdf_bytes(content: bytes) -> None:
        """Verify PDF magic bytes and size constraints."""
        if len(content) == 0:
            raise PDFProcessingError("Uploaded file is empty (0 bytes).")

        if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
            max_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise PDFProcessingError(f"File size exceeds maximum permitted limit of {max_mb} MB.")

        # Check first 1024 bytes for PDF signature
        header_sample = content[:1024]
        if PDF_MAGIC_BYTES not in header_sample:
            raise PDFProcessingError("Invalid file signature: Not a valid PDF document.")

    @classmethod
    def extract_text(cls, source: Union[bytes, Path, str]) -> ExtractedDocument:
        """Extract text page-by-page from raw bytes or a file path using PyMuPDF."""
        doc = None
        try:
            if isinstance(source, bytes):
                cls.validate_pdf_bytes(source)
                doc = pymupdf.open(stream=source, filetype="pdf")
            else:
                path = Path(source).resolve()
                if not path.exists():
                    raise PDFProcessingError(f"Document file not found at: {path}")
                with open(path, "rb") as f:
                    header = f.read(1024)
                if PDF_MAGIC_BYTES not in header:
                    raise PDFProcessingError("Invalid file signature: Not a valid PDF document.")
                doc = pymupdf.open(path)

            page_count = len(doc)
            if page_count == 0:
                raise PDFProcessingError("PDF document has 0 pages.")

            extracted_pages: List[ExtractedPage] = []
            total_chars = 0

            for page_index in range(page_count):
                page = doc.load_page(page_index)
                raw_text = page.get_text("text") or ""
                # Normalize line breaks and clean whitespace
                cleaned_text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
                char_count = len(cleaned_text)
                total_chars += char_count

                extracted_pages.append(
                    ExtractedPage(
                        page_number=page_index + 1,
                        text=cleaned_text,
                        char_count=char_count,
                    )
                )

            logger.info(
                "PDF extracted successfully",
                extra={
                    "page_count": page_count,
                    "total_characters": total_chars,
                },
            )

            return ExtractedDocument(
                page_count=page_count,
                pages=extracted_pages,
                total_characters=total_chars,
            )

        except PDFProcessingError:
            raise
        except Exception as e:
            logger.error(f"PyMuPDF text extraction failed: {str(e)}", exc_info=True)
            raise PDFProcessingError(f"Corrupted or unreadable PDF: {str(e)}") from e
        finally:
            if doc is not None:
                doc.close()
