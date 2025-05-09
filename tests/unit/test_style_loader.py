from pathlib import Path

from app.core.config import settings
from app.services.style_loader import load_style_samples


def setup_function():
    # Ensure cache is cleared before each test
    load_style_samples.cache_clear()


def test_load_style_samples_no_dir(monkeypatch):
    # Point reference_dir to a non-existent path
    monkeypatch.setattr(
        settings, "reference_dir", Path("nonexistent_dir"), raising=False
    )
    result = load_style_samples()
    assert result == ""


def test_load_style_samples_skip_corrupt(monkeypatch, tmp_path):
    # Create temp reference_dir with one .docx file
    docx_file = tmp_path / "bad.docx"
    docx_file.write_bytes(b"not a valid docx")
    monkeypatch.setattr(settings, "reference_dir", tmp_path, raising=False)
    # Make Document raise for corrupt file
    monkeypatch.setattr(
        "app.services.style_loader.Document",
        lambda path: (_ for _ in ()).throw(Exception("bad docx")),
    )
    result = load_style_samples()
    assert result == ""


def test_load_style_samples_success(monkeypatch, tmp_path):
    # Create temp reference_dir with one .docx file
    docx_file = tmp_path / "good.docx"
    docx_file.write_bytes(b"ignored contents")
    monkeypatch.setattr(settings, "reference_dir", tmp_path, raising=False)

    # Fake Document to return paragraphs with text
    class FakePara:
        def __init__(self, text):
            self.text = text

    class FakeDoc:
        def __init__(self, path):
            self.paragraphs = [FakePara("Para1"), FakePara("Para2")]

    monkeypatch.setattr("app.services.style_loader.Document", FakeDoc)
    result = load_style_samples()
    # Ensure paragraphs are joined and returned
    assert "Para1" in result and "Para2" in result
