"""Tests for ASD-STE100 STE flag and validator."""

from pathlib import Path

import pytest

from paperful.config import (
    Config,
    load_config,
    parse_ste_violation_policy,
    parse_summarize_style,
)
from paperful.ste import STEValidator, extract_domain_words
from paperful.summarize import (
    _enforce_ste,
    _validate_ste,
    current_prompt_sha,
    load_prompt_template,
)


class TestSTEValidator:
    """Unit tests for STEValidator."""

    def test_sentence_too_long(self):
        """Sentence exceeding 25 words should be flagged."""
        validator = STEValidator()
        html = (
            "<p>This is a very long sentence that contains significantly more "
            "than twenty five words in total and should definitely be flagged "
            "as a violation of the rule.</p>"
        )
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
        html = (
            "<p>Sentence one. Sentence two. Sentence three. Sentence four. "
            "Sentence five. Sentence six. Sentence seven.</p>"
        )
        violations = validator.check_summary(html)
        assert any(v.rule == "paragraph_length" for v in violations)

    def test_paragraph_within_limit(self):
        """Paragraph with 6 or fewer sentences should not be flagged."""
        validator = STEValidator()
        html = "<p>Sentence one. Sentence two. Sentence three.</p>"
        violations = validator.check_summary(html)
        assert not any(v.rule == "paragraph_length" for v in violations)

    def test_domain_words_excluded(self, tmp_path: Path):
        """Words in domain_words set should not be flagged."""
        word_list = tmp_path / "ste_words.txt"
        word_list.write_text("test\napproved\n", encoding="utf-8")
        validator = STEValidator(word_list)
        html = "<p>Test approved system.</p>"
        violations = validator.check_summary(html, domain_words={"system"})
        assert not any(v.rule == "vocabulary" for v in violations)

    def test_vocabulary_flags_many_unapproved(self, tmp_path: Path):
        """Many unapproved words still produce a vocabulary violation."""
        word_list = tmp_path / "ste_words.txt"
        word_list.write_text("the\na\n", encoding="utf-8")
        validator = STEValidator(word_list)
        html = "<p>Alpha bravo charlie delta echo foxtrot golf.</p>"
        violations = validator.check_summary(html)
        vocab = [v for v in violations if v.rule == "vocabulary"]
        assert vocab
        assert "more" in vocab[0].message

    def test_missing_word_list_raises(self, tmp_path: Path):
        missing = tmp_path / "missing.txt"
        with pytest.raises(FileNotFoundError, match="STE word list"):
            STEValidator(missing)


class TestSTEPromptIntegration:
    """Test STE flag integration with prompt loading."""

    def test_ste_flag_defaults_to_plain(self):
        """summarize_style should default to 'plain'."""
        cfg = Config()
        assert cfg.summarize_style == "plain"
        assert cfg.ste_violation_policy == "warn"

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
    """Test validation function and policy enforcement."""

    def test_validate_ste_disabled_in_plain_mode(self):
        """_validate_ste should return empty list when summarize_style='plain'."""
        cfg = Config(summarize_style="plain")
        html = (
            "<p>Some problematic text with very long sentences that exceed "
            "the limit significantly.</p>"
        )
        violations = _validate_ste(cfg, html)
        assert violations == []

    def test_validate_ste_enabled_in_ste_mode(self):
        """_validate_ste should check violations when summarize_style='ste'."""
        cfg = Config(summarize_style="ste")
        html = (
            "<p>This is a very long sentence that contains more than twenty "
            "five words in total and should definitely be flagged as a "
            "violation.</p>"
        )
        violations = _validate_ste(cfg, html)
        assert len(violations) > 0

    def test_enforce_ste_warn_emits_warning(self):
        cfg = Config(summarize_style="ste", ste_violation_policy="warn")
        html = (
            "<p>This is a very long sentence that contains more than twenty "
            "five words in total and should definitely be flagged as a "
            "violation.</p>"
        )
        with pytest.warns(UserWarning, match="STE violations"):
            _enforce_ste(cfg, html, item_key="ABCD1234")

    def test_enforce_ste_fail_raises(self):
        cfg = Config(summarize_style="ste", ste_violation_policy="fail")
        html = (
            "<p>This is a very long sentence that contains more than twenty "
            "five words in total and should definitely be flagged as a "
            "violation.</p>"
        )
        with pytest.raises(ValueError, match="STE violations \\(ABCD1234\\)"):
            _enforce_ste(cfg, html, item_key="ABCD1234")

    def test_enforce_ste_noop_in_plain_mode(self):
        cfg = Config(summarize_style="plain", ste_violation_policy="fail")
        html = (
            "<p>This is a very long sentence that contains more than twenty "
            "five words in total and should definitely be flagged as a "
            "violation.</p>"
        )
        _enforce_ste(cfg, html, item_key="ABCD1234")


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


class TestSTEConfigParse:
    """Config parsers and TOML wiring for STE knobs."""

    def test_parse_summarize_style(self):
        assert parse_summarize_style("STE") == "ste"
        assert parse_summarize_style("") == "plain"
        with pytest.raises(ValueError, match="plain or ste"):
            parse_summarize_style("fancy")

    def test_parse_ste_violation_policy(self):
        assert parse_ste_violation_policy("FAIL") == "fail"
        assert parse_ste_violation_policy("") == "warn"
        with pytest.raises(ValueError, match="warn or fail"):
            parse_ste_violation_policy("ignore")

    def test_toml_loads_ste_keys(self, tmp_path: Path):
        words = tmp_path / "words.txt"
        words.write_text("the\na\n", encoding="utf-8")
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            f"""
[summarize]
style = "ste"
ste_violation_policy = "fail"
ste_word_list_path = "{words.name}"
""",
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        assert cfg.summarize_style == "ste"
        assert cfg.ste_violation_policy == "fail"
        assert cfg.ste_word_list_path == words.resolve()
