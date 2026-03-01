"""
PDF extraction using PyPDF2 (primary) and Gemini (fallback for scanned/complex PDFs).
"""

import logging
import streamlit as st
import google.generativeai as genai
import PyPDF2

logger = logging.getLogger(__name__)

# Minimum chars for PyPDF2 to be considered successful
_MIN_EXTRACTION_CHARS = 200


def extract_pdf_text(pdf_file) -> str:
    """Extract text from PDF. Uses PyPDF2 first (free, fast). Falls back to Gemini
    only if PyPDF2 produces very little text (e.g. scanned/image-based PDFs)."""
    text = _extract_with_pypdf2(pdf_file)

    if len(text.strip()) >= _MIN_EXTRACTION_CHARS:
        return text

    # PyPDF2 got very little — likely a scanned/image PDF, try Gemini
    if text.strip():
        logger.info(f"PyPDF2 extracted only {len(text.strip())} chars, trying Gemini fallback")
        st.info("Text extraction produced limited results. Trying AI-powered extraction...")
    else:
        logger.info("PyPDF2 extracted no text, trying Gemini fallback")
        st.info("No text found with standard extraction. Trying AI-powered extraction...")

    gemini_text = _extract_with_gemini(pdf_file)
    return gemini_text if gemini_text else text


def _extract_with_pypdf2(pdf_file) -> str:
    """Primary PDF extraction using PyPDF2 (free, no API calls)."""
    try:
        pdf_file.seek(0)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text()
            if page_text and page_text.strip():
                text += f"\n{'='*50}\nPAGE {i+1}\n{'='*50}\n{page_text}\n"
        return text if text.strip() else ""
    except Exception as e:
        logger.error(f"PyPDF2 extraction error: {e}")
        return ""


def _extract_with_gemini(pdf_file) -> str:
    """Fallback PDF extraction using Gemini (for scanned/image-based PDFs)."""
    try:
        pdf_file.seek(0)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        pdf_file.seek(0)
        uploaded_file = genai.upload_file(pdf_file, mime_type='application/pdf')

        prompt = """Extract ALL text content from this PDF document.
        Include everything: headers, body text, tables, numbers, charts, footnotes.
        Be extremely thorough."""

        response = model.generate_content([uploaded_file, prompt])
        return response.text
    except Exception as e:
        logger.error(f"Gemini extraction error: {e}")
        st.error("PDF text extraction failed. Please ensure the PDF contains readable text.")
        return ""


# Keep old name as alias for backward compatibility
extract_pdf_with_gemini = extract_pdf_text
