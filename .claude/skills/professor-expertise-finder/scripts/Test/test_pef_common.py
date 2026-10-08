import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import pef_common  # noqa: E402
from pef_common import data_root, load_config, name_key, norm, slugify  # noqa: E402


def test_slugify_strips_accents_and_collapses():
    assert slugify("France, Île-de-France") == "france-ile-de-france"
    assert slugify("   ") == "unspecified"


def test_norm_folds_case_accent_and_punctuation():
    assert norm("É. Doe-Smith") == "e doe smith"
    assert norm(None) == ""


def test_name_key_is_order_insensitive():
    assert name_key("Jane Doe") == name_key("Doe, Jane")
    assert name_key("Jane Doe") != name_key("Jane Doey")


def test_data_root_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("PROFESSOR_EXPERTISE_DATA", raising=False)
    assert data_root() == pef_common.DEFAULT_DATA_ROOT


def test_data_root_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFESSOR_EXPERTISE_DATA", str(tmp_path))
    assert data_root() == tmp_path


def test_load_config_reads_the_shipped_file():
    config = load_config()
    assert config["subscore_values"] == [0, 0.5, 1]
    assert config["max_per_university"] == 1
    assert config["retain_threshold"] == 1.5


def test_load_config_missing_file_raises(monkeypatch):
    monkeypatch.setattr(pef_common, "CONFIG_PATH", Path("/does/not/exist.json"))
    with pytest.raises(FileNotFoundError):
        load_config()


def test_load_config_malformed_json_raises(tmp_path, monkeypatch):
    bad = tmp_path / "pef_config.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(pef_common, "CONFIG_PATH", bad)
    with pytest.raises(ValueError):
        load_config()


def test_load_config_missing_key_raises(tmp_path, monkeypatch):
    incomplete = tmp_path / "pef_config.json"
    incomplete.write_text(json.dumps({"subscore_values": [0, 0.5, 1]}), encoding="utf-8")
    monkeypatch.setattr(pef_common, "CONFIG_PATH", incomplete)
    with pytest.raises(ValueError):
        load_config()
