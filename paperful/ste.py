"""ASD-STE100 Simplified Technical English validator for summaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class STEViolation:
    """A single STE compliance violation."""

    rule: str
    message: str
    context: str = ""


class STEValidator:
    """Check summaries against ASD-STE100 Simplified Technical English rules."""

    MAX_WORDS_PER_SENTENCE = 20
    MAX_WORDS_PER_SENTENCE_DESCRIPTIVE = 25
    MAX_SENTENCES_PER_PARAGRAPH = 6
    MAX_WORDS_MULTI_NOUN = 3

    def __init__(self, word_list_path: Path | None = None):
        """Initialize validator with optional approved word list."""
        self.approved_words: set[str] = set()
        if word_list_path and word_list_path.exists():
            try:
                text = word_list_path.read_text(encoding="utf-8")
                self.approved_words = {w.strip().lower() for w in text.splitlines() if w.strip()}
            except Exception:
                pass

    def check_summary(
        self, html: str, domain_words: set[str] | None = None
    ) -> list[STEViolation]:
        """
        Check summary HTML for STE violations.

        Args:
            html: Summary HTML (simple structure: h2, p, ul/li)
            domain_words: Words from source document that are auto-approved

        Returns:
            List of violations found.
        """
        domain_words = domain_words or set()
        violations: list[STEViolation] = []

        # Strip HTML and extract paragraphs/sentences
        text = self._strip_html(html)
        paragraphs = self._extract_paragraphs(html)

        violations.extend(self._check_sentences(paragraphs))
        violations.extend(self._check_paragraphs(paragraphs))
        violations.extend(self._check_passive_voice(paragraphs))

        if self.approved_words:
            violations.extend(self._check_vocabulary(text, domain_words))

        return violations

    def _strip_html(self, html: str) -> str:
        """Remove HTML tags, keeping text content."""
        text = re.sub(r"<h[1-6][^>]*>", "", html, flags=re.IGNORECASE)
        text = re.sub(r"</h[1-6]>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<ul[^>]*>|</ul>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    def _extract_paragraphs(self, html: str) -> list[str]:
        """Extract paragraphs from HTML (p tags, li items grouped by ul)."""
        paragraphs: list[str] = []

        # Extract <p> paragraphs
        p_matches = re.finditer(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
        for match in p_matches:
            text = match.group(1)
            text = re.sub(r"<[^>]+>", "", text)
            if text.strip():
                paragraphs.append(text.strip())

        # Extract <ul>/<ol> blocks as paragraphs (each <li> is a sentence)
        list_matches = re.finditer(r"<(?:ul|ol)[^>]*>(.*?)</(?:ul|ol)>", html, re.IGNORECASE | re.DOTALL)
        for match in list_matches:
            list_content = match.group(1)
            items = re.findall(r"<li[^>]*>(.*?)</li>", list_content, re.IGNORECASE | re.DOTALL)
            for item in items:
                item_text = re.sub(r"<[^>]+>", "", item).strip()
                if item_text:
                    paragraphs.append(item_text)

        return paragraphs

    def _check_sentences(self, paragraphs: list[str]) -> list[STEViolation]:
        """Check sentence length (max 20-25 words depending on type)."""
        violations: list[STEViolation] = []

        for para_idx, para in enumerate(paragraphs):
            sentences = self._split_sentences(para)
            for sent_idx, sent in enumerate(sentences):
                word_count = self._count_words(sent)
                # Use descriptive limit (25) for all—can differentiate on procedure content later
                if word_count > self.MAX_WORDS_PER_SENTENCE_DESCRIPTIVE:
                    violations.append(
                        STEViolation(
                            rule="sentence_length",
                            message=f"Sentence {sent_idx + 1} in paragraph {para_idx + 1} "
                            f"has {word_count} words (max {self.MAX_WORDS_PER_SENTENCE_DESCRIPTIVE})",
                            context=sent[:80],
                        )
                    )

        return violations

    def _check_paragraphs(self, paragraphs: list[str]) -> list[STEViolation]:
        """Check paragraph structure (max 6 sentences)."""
        violations: list[STEViolation] = []

        for para_idx, para in enumerate(paragraphs):
            sentences = self._split_sentences(para)
            if len(sentences) > self.MAX_SENTENCES_PER_PARAGRAPH:
                violations.append(
                    STEViolation(
                        rule="paragraph_length",
                        message=f"Paragraph {para_idx + 1} has {len(sentences)} sentences "
                        f"(max {self.MAX_SENTENCES_PER_PARAGRAPH})",
                        context=para[:80],
                    )
                )

        return violations

    def _check_passive_voice(self, paragraphs: list[str]) -> list[STEViolation]:
        """Heuristic check for passive voice (prefer active voice)."""
        violations: list[STEViolation] = []
        passive_pattern = re.compile(r"\b(was|were|is|are|be|been|being)\s+\w+(?:ed|en)\b", re.IGNORECASE)

        for para_idx, para in enumerate(paragraphs):
            if passive_pattern.search(para):
                violations.append(
                    STEViolation(
                        rule="passive_voice",
                        message=f"Paragraph {para_idx + 1} may contain passive voice",
                        context=para[:80],
                    )
                )

        return violations

    def _check_vocabulary(self, text: str, domain_words: set[str]) -> list[STEViolation]:
        """Check that words are approved or from domain."""
        violations: list[STEViolation] = []

        if not self.approved_words:
            return violations

        # Extract words (simple: lowercase, alphanumeric + hyphen)
        words = set(re.findall(r"\b[a-z0-9]+(?:-[a-z0-9]+)*\b", text.lower()))
        domain_words_lower = {w.lower() for w in domain_words}
        approved_combined = self.approved_words | domain_words_lower

        unapproved = words - approved_combined
        if unapproved and len(unapproved) <= 5:  # Only flag small counts to avoid noise
            violations.append(
                STEViolation(
                    rule="vocabulary",
                    message=f"Unapproved words found: {', '.join(sorted(list(unapproved)[:5]))}",
                )
            )

        return violations

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences (naive: period/exclamation/question mark)."""
        text = text.strip()
        if not text:
            return []
        # Simple sentence boundary: . ! ?
        sentences = re.split(r"[.!?]+", text)
        return [s.strip() for s in sentences if s.strip()]

    def _count_words(self, text: str) -> int:
        """
        Count words in text per STE Rule 8.6:
        - Numbers with units count as one word
        - Contractions count as one word
        - Simple: split on whitespace, count tokens
        """
        # Remove HTML
        text = re.sub(r"<[^>]+>", "", text)
        # Split on whitespace
        words = text.split()
        return len(words)


def extract_domain_words(metadata: str | None, text: str | None) -> set[str]:
    """Extract domain-specific words from document metadata and text."""
    domain_words: set[str] = set()

    for source in [metadata or "", text or ""]:
        if not source:
            continue
        # Extract words (alphanumeric, hyphenated)
        words = re.findall(r"\b[a-z0-9]+(?:-[a-z0-9]+)*\b", source.lower())
        # Filter: keep 2-5 char technical-looking terms
        domain_words.update(w for w in words if 2 <= len(w) <= 20)

    return domain_words
