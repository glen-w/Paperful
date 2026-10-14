"""Tests for ASD-STE100 STE flag and validator."""

import hashlib
from pathlib import Path

import pytest

from paperful.config import Config
from paperful.ste import STEValidator, extract_domain_words
from paperful.summarize import load_prompt_template, current_prompt_sha, _validate_ste


class TestSTEValidator:
    """Unit tests for STEValidator."""

    def test_sentence_too_long(self):
        """Sentence exceeding 25 words should be flagged."""
        validator = STEValidator()
        html = "<p>This is a very long sentence that contains significantly more than twenty five words in total and should definitely be flagged as a violation of the rule.</p>"
        violations = validator.check_summary(html)
        assert any(v.rule == "sentence_length" for v in violations)

    def test_sentence_within_limit(self):
        """Sentence under 25 words should not be flagged."""
        validator = STEValidator()
        html = "<p>This is a short sentence.</p>"
        violations = validator.check_summary(html)
        assert not any(v.rule == "sentence_length" for v in violations)

    def test_paragraph_too_long(self):
        """Paragraph with more than 6 sentences should be flagged."""
        validator = STEValidator()
        html = "<p>Sentence one. Sentence two. Sentence three. Sentence four. Sentence five. Sentence six. Sentence seven.</p>"
        violations = validator.check_summary(html)
        assert any(v.rule == "paragraph_length" for v in violations)

    def test_paragraph_within_limit(self):
        """Paragraph with 6 or fewer sentences should not be flagged."""
        validator = STEValidator()
        html = "<p>Sentence one. Sentence two. Sentence three.</p>"
        violations = validator.check_summary(html)
        assert not any(v.rule == "paragraph_length" for v in violations)

    def test_domain_words_excluded(self):
        """Words in domain_words set should not be flagged."""
        word_list = Path("/tmp/test_ste_words.txt")
        word_list.write_text("test\napproved\n")
        try:
            validator = STEValidator(word_list)
            html = "<p>Test approved system.</p>"
            violations = validator.check_summary(html, domain_words={"system"})
            # Should not have vocabulary violations
            assert not any(v.rule == "vocabulary" for v in violations)
        finally:
            word_list.unlink()


class TestSTEPromptIntegration:
    """Test STE flag integration with prompt loading."""

    def test_ste_flag_defaults_to_plain(self):
        """summarize_style should default to 'plain'."""
        cfg = Config()
        assert cfg.summarize_style == "plain"

    def test_ste_rules_block_appended_when_enabled(self):
        """STE rules block should be appended when summarize_style='ste'."""
        cfg = Config(summarize_style="plain")
        plain_template, _ = load_prompt_template(cfg)

        cfg.summarize_style = "ste"
        ste_template, _ = load_prompt_template(cfg)

        assert len(ste_template) > len(plain_template)
        assert "Simplified Technical English" in ste_template

    def test_ste_prompt_block_not_in_plain_mode(self):
        """STE rules block should not be in plain mode."""
        cfg = Config(summarize_style="plain")
        template, _ = load_prompt_template(cfg)
        assert "Simplified Technical English" not in template

    def test_sha_changes_when_ste_toggled(self):
        """SHA should change when summarize_style is toggled."""
        cfg = Config(summarize_style="plain")
        plain_sha = current_prompt_sha(cfg)

        cfg.summarize_style = "ste"
        ste_sha = current_prompt_sha(cfg)

        assert plain_sha != ste_sha

    def test_sha_consistent_same_mode(self):
        """SHA should be same when mode doesn't change."""
        cfg = Config(summarize_style="ste")
        sha1 = current_prompt_sha(cfg)
        sha2 = current_prompt_sha(cfg)
        assert sha1 == sha2


class TestSTEValidation:
    """Test validation function."""

    def test_validate_ste_disabled_in_plain_mode(self):
        """_validate_ste should return empty list when summarize_style='plain'."""
        cfg = Config(summarize_style="plain")
        html = "<p>Some problematic text with very long sentences that exceed the limit significantly.</p>"
        violations = _validate_ste(cfg, html)
        assert violations == []

    def test_validate_ste_enabled_in_ste_mode(self):
        """_validate_ste should check violations when summarize_style='ste'."""
        cfg = Config(summarize_style="ste")
        html = "<p>This is a very long sentence that contains more than twenty five words in total and should definitely be flagged as a violation.</p>"
        violations = _validate_ste(cfg, html)
        assert len(violations) > 0


class TestExtractDomainWords:
    """Test domain word extraction."""

    def test_extract_from_metadata(self):
        """Should extract words from metadata."""
        words = extract_domain_words("machine learning algorithm", None)
        assert "machine" in words
        assert "learning" in words
        assert "algorithm" in words

    def test_extract_from_text(self):
        """Should extract words from document text."""
        words = extract_domain_words(None, "quantum entanglement measurement")
        assert "quantum" in words
        assert "entanglement" in words
        assert "measurement" in words

    def test_extract_filters_short_words(self):
        """Should filter words shorter than 2 chars."""
        words = extract_domain_words("a very important concept", None)
        assert "a" not in words
        assert "very" in words
        assert "important" in words
        assert "concept" in words
