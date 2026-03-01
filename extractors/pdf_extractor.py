"""
PDF extraction using Gemini (primary) and PyPDF2 (fallback).
"""

import streamlit as st
import google.generativeai as genai
import PyPDF2


def extract_pdf_with_gemini(pdf_file) -> str:
    """Use Gemini's native PDF processing."""
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
        st.error(f"Gemini extraction error: {e}")
        return extract_pdf_with_pypdf2(pdf_file)


def extract_pdf_with_pypdf2(pdf_file) -> str:
    """Fallback PDF extraction using PyPDF2."""
    try:
        pdf_file.seek(0)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text()
            if page_text.strip():
                text += f"\n{'='*50}\nPAGE {i+1}\n{'='*50}\n{page_text}\n"
        return text if text.strip() else ""
    except Exception as e:
        st.error(f"PyPDF2 error: {e}")
        return ""
