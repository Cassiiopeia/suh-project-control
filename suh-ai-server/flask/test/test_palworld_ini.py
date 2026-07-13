"""test_palworld_ini.py"""
import pytest
from service.palworld_ini import parse_option_settings, update_option_settings

SAMPLE = '''[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,ServerName="My, Server",ServerPassword="",ServerPlayerMaxNum=32,bCrossplay=False,RESTAPIEnabled=True)
'''


def test_parse_basic_values():
    result = parse_option_settings(SAMPLE)
    assert result["Difficulty"] == "None"
    assert result["ServerPlayerMaxNum"] == "32"
    assert result["bCrossplay"] == "False"


def test_parse_quoted_string_with_comma():
    result = parse_option_settings(SAMPLE)
    assert result["ServerName"] == '"My, Server"'


def test_parse_missing_option_settings_raises():
    with pytest.raises(ValueError):
        parse_option_settings("[/Script/Pal.PalGameWorldSettings]\n")


def test_update_preserves_other_keys_and_lines():
    updated = update_option_settings(SAMPLE, {"ServerPlayerMaxNum": "16"})
    result = parse_option_settings(updated)
    assert result["ServerPlayerMaxNum"] == "16"
    assert result["ServerName"] == '"My, Server"'
    assert updated.startswith("[/Script/Pal.PalGameWorldSettings]")


def test_update_wraps_string_keys_in_quotes():
    updated = update_option_settings(SAMPLE, {"ServerName": "팰 사냥터"})
    result = parse_option_settings(updated)
    assert result["ServerName"] == '"팰 사냥터"'


def test_update_boolean_passthrough():
    updated = update_option_settings(SAMPLE, {"bCrossplay": "True"})
    assert parse_option_settings(updated)["bCrossplay"] == "True"


def test_roundtrip_no_changes_is_identical():
    assert update_option_settings(SAMPLE, {}) == SAMPLE
