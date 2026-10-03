"""The prompt loader must fail loudly: a half-filled prompt is a tutor that ignores the profile."""
import pytest

from app.prompts import PromptError, placeholders, render


def test_render_substitutes_every_placeholder(tmp_path, monkeypatch):
    from app.config import settings
    from app.prompts import _read

    monkeypatch.setattr(settings, "prompts_dir", tmp_path)
    _read.cache_clear()
    (tmp_path / "t.md").write_text("Level {{level}}, unit {{unit}}. Again: {{level}}.")
    assert render("t", level="A1.2", unit="Beim Arzt") == "Level A1.2, unit Beim Arzt. Again: A1.2."
    _read.cache_clear()


def test_missing_and_extra_keys_raise(tmp_path, monkeypatch):
    from app.config import settings
    from app.prompts import _read

    monkeypatch.setattr(settings, "prompts_dir", tmp_path)
    _read.cache_clear()
    (tmp_path / "t.md").write_text("Level {{level}}")
    with pytest.raises(PromptError, match="level"):
        render("t")
    with pytest.raises(PromptError, match="typo"):
        render("t", level="A1", typo="x")
    _read.cache_clear()


def test_unknown_prompt_file_raises():
    with pytest.raises(PromptError):
        render("no_such_prompt")


def test_shipped_tutor_prompt_declares_the_profile_it_needs():
    """If this list changes, the tutor service must pass the new value — it will raise otherwise."""
    assert placeholders("tutor_talk") == {
        "level", "unit_title", "unit_goals", "grammar_targets", "top_mistakes",
        "due_vocab", "facts", "rolling_summary", "scenario",
    }
