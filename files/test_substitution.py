"""Tests for adcp.substitution — encode_unreserved and universal_macro_translation.

Covers:
* RFC-3986 unreserved charset encoding (encode_unreserved)
* Macro substitution via value-entry (encode_unreserved applied)
* Native-entry passthrough (verbatim)
* Unmapped macro → param dropped + recorded in unmapped_macros
* Non-macro params pass through unchanged
* Deduplication of unmapped_macros when the same macro appears twice
* Partial macro literals are not substituted
* UTF-8 multi-byte encoding in value entries
* Golden test vectors from static/test-vectors/universal-macro-translation.json
"""

from __future__ import annotations

import json
import pathlib

import pytest

from adcp.substitution import (
    MacroTranslationResult,
    encode_unreserved,
    universal_macro_translation,
)
from adcp.types._generated import UniversalMacro


# ---------------------------------------------------------------------------
# encode_unreserved
# ---------------------------------------------------------------------------


class TestEncodeUnreserved:
    def test_alpha_digits_unreserved(self) -> None:
        """All ALPHA + DIGIT characters must be left unencoded."""
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        assert encode_unreserved(chars) == chars

    def test_special_unreserved_symbols(self) -> None:
        """Hyphen, dot, underscore, tilde are unreserved and must not be encoded."""
        assert encode_unreserved("-._~") == "-._~"

    def test_space_encoded(self) -> None:
        """Space is not unreserved — must become %20 (not +)."""
        assert encode_unreserved(" ") == "%20"

    def test_slash_encoded(self) -> None:
        """Forward slash is a reserved character — must become %2F."""
        assert encode_unreserved("/") == "%2F"

    def test_colon_encoded(self) -> None:
        """Colon is reserved — must become %3A."""
        assert encode_unreserved(":") == "%3A"

    def test_at_encoded(self) -> None:
        """@ is reserved — must become %40."""
        assert encode_unreserved("@") == "%40"

    def test_ampersand_encoded(self) -> None:
        """& is reserved — must become %26."""
        assert encode_unreserved("&") == "%26"

    def test_equals_encoded(self) -> None:
        """= is reserved — must become %3D."""
        assert encode_unreserved("=") == "%3D"

    def test_question_mark_encoded(self) -> None:
        """? is reserved — must become %3F."""
        assert encode_unreserved("?") == "%3F"

    def test_percent_itself_encoded(self) -> None:
        """% must become %25 so pre-encoded input doesn't pass through unencoded."""
        assert encode_unreserved("%") == "%25"

    def test_uppercase_hex_in_output(self) -> None:
        """Percent-encoded escapes must use uppercase hex digits."""
        # NUL is a single UTF-8 byte (0x00)
        assert encode_unreserved("\x00") == "%00"
        # DEL is a single UTF-8 byte (0x7F)
        assert encode_unreserved("\x7f") == "%7F"
        # U+00FF (ÿ) is two UTF-8 bytes: 0xC3 0xBF
        assert encode_unreserved("\xff") == "%C3%BF"

    def test_utf8_multibyte(self) -> None:
        """Non-ASCII characters are UTF-8 encoded then each byte percent-encoded."""
        # ã = U+00E3, UTF-8 = 0xC3 0xA3
        assert encode_unreserved("ã") == "%C3%A3"

    def test_full_url_encoded(self) -> None:
        """A complete URL becomes fully percent-encoded (scheme, slashes, etc.)."""
        result = encode_unreserved("https://example.com/path?q=1")
        assert "%" in result
        assert "://" not in result

    def test_empty_string(self) -> None:
        assert encode_unreserved("") == ""

    def test_tilde_not_encoded(self) -> None:
        """Tilde is explicitly in the RFC-3986 unreserved set."""
        assert encode_unreserved("v1~beta") == "v1~beta"

    def test_curly_braces_encoded(self) -> None:
        """{ and } are not unreserved — they must be percent-encoded."""
        result = encode_unreserved("${MACRO}")
        assert result == "%24%7BMACRO%7D"


# ---------------------------------------------------------------------------
# universal_macro_translation
# ---------------------------------------------------------------------------


class TestUniversalMacroTranslation:
    def test_value_entry_substituted_and_encoded(self) -> None:
        url = "https://px.example.com/fire?mbid=${MEDIA_BUY_ID}"
        result = universal_macro_translation(url, {"MEDIA_BUY_ID": {"value": "mb-001"}})
        assert result.url == "https://px.example.com/fire?mbid=mb-001"
        assert result.dropped_params == []
        assert result.unmapped_macros == []

    def test_value_entry_special_chars_encoded(self) -> None:
        url = "https://px.example.com/fire?ua=${USER_AGENT}"
        ua = "Mozilla/5.0 (Windows NT 10.0)"
        result = universal_macro_translation(url, {"USER_AGENT": {"value": ua}})
        assert "Mozilla" in result.url
        assert " " not in result.url
        assert "/" not in result.url.split("?", 1)[1]

    def test_native_entry_inserted_verbatim(self) -> None:
        url = "https://px.example.com/fire?click=${CLICK_URL}"
        token = "https%3A%2F%2Fclick.example.com%3Fid%3D1"
        result = universal_macro_translation(url, {"CLICK_URL": {"native": token}})
        assert result.url == f"https://px.example.com/fire?click={token}"

    def test_unmapped_macro_drops_param(self) -> None:
        url = "https://px.example.com/fire?mbid=${MEDIA_BUY_ID}&cb=${CACHEBUSTER}"
        result = universal_macro_translation(url, {"MEDIA_BUY_ID": {"value": "mb-1"}})
        assert "mbid=mb-1" in result.url
        assert "cb=" not in result.url
        assert result.dropped_params == ["cb"]
        assert result.unmapped_macros == ["CACHEBUSTER"]

    def test_non_macro_param_passthrough(self) -> None:
        url = "https://px.example.com/fire?static=literal&encoded=hello%20world"
        result = universal_macro_translation(url, {})
        assert result.url == url
        assert result.dropped_params == []
        assert result.unmapped_macros == []

    def test_partial_macro_literal(self) -> None:
        url = "https://px.example.com/fire?tag=prefix_${CREATIVE_ID}_suffix"
        result = universal_macro_translation(url, {"CREATIVE_ID": {"value": "cr-99"}})
        # Partial macro is not substituted — passes through unchanged.
        assert "prefix_${CREATIVE_ID}_suffix" in result.url
        assert result.dropped_params == []
        assert result.unmapped_macros == []

    def test_empty_mapping_drops_all_macros(self) -> None:
        url = "https://px.example.com/fire?a=${MEDIA_BUY_ID}&b=${CREATIVE_ID}"
        result = universal_macro_translation(url, {})
        assert result.url == "https://px.example.com/fire"
        assert result.dropped_params == ["a", "b"]
        assert "MEDIA_BUY_ID" in result.unmapped_macros
        assert "CREATIVE_ID" in result.unmapped_macros

    def test_same_macro_two_params_dedup(self) -> None:
        url = "https://px.example.com/fire?x=${CACHEBUSTER}&y=${CACHEBUSTER}"
        result = universal_macro_translation(url, {})
        assert result.dropped_params == ["x", "y"]
        assert result.unmapped_macros == ["CACHEBUSTER"]

    def test_no_query_string_unchanged(self) -> None:
        url = "https://px.example.com/fire"
        result = universal_macro_translation(url, {"MEDIA_BUY_ID": {"value": "x"}})
        assert result.url == url
        assert result.dropped_params == []
        assert result.unmapped_macros == []

    def test_enum_key_in_mapping(self) -> None:
        url = "https://px.example.com/fire?mbid=${MEDIA_BUY_ID}"
        result = universal_macro_translation(
            url,
            {UniversalMacro.MEDIA_BUY_ID: {"value": "mb-enum"}},
        )
        assert "mbid=mb-enum" in result.url

    def test_string_and_enum_key_interchangeable(self) -> None:
        """StrEnum equality means a string key finds an enum-keyed entry and vice versa."""
        url = "https://px.example.com/fire?cid=${CREATIVE_ID}"
        result_str = universal_macro_translation(url, {"CREATIVE_ID": {"value": "cr-1"}})
        result_enum = universal_macro_translation(
            url,
            {UniversalMacro.CREATIVE_ID: {"value": "cr-1"}},
        )
        assert result_str.url == result_enum.url

    def test_mixed_substitution(self) -> None:
        url = (
            "https://px.example.com/fire"
            "?cid=${CREATIVE_ID}&gdpr=${GDPR_CONSENT}&cb=${CACHEBUSTER}&sid=session42"
        )
        result = universal_macro_translation(
            url,
            {
                "CREATIVE_ID": {"value": "cr-99"},
                "GDPR_CONSENT": {"native": "CPzHq4A"},
            },
        )
        assert "cid=cr-99" in result.url
        assert "gdpr=CPzHq4A" in result.url
        assert "sid=session42" in result.url
        assert "cb=" not in result.url
        assert result.dropped_params == ["cb"]
        assert result.unmapped_macros == ["CACHEBUSTER"]

    def test_utf8_value_encoding(self) -> None:
        url = "https://px.example.com/fire?city=${CITY}"
        result = universal_macro_translation(url, {"CITY": {"value": "São Paulo"}})
        # ã = U+00E3 → %C3%A3; space → %20
        assert "city=S%C3%A3o%20Paulo" in result.url

    def test_result_type(self) -> None:
        result = universal_macro_translation("https://px.example.com/", {})
        assert isinstance(result, MacroTranslationResult)

    def test_url_value_fully_encoded(self) -> None:
        url = "https://px.example.com/fire?dest=${CLICK_URL}"
        dest = "https://destination.example.com/land?id=42&ref=adcp"
        result = universal_macro_translation(url, {"CLICK_URL": {"value": dest}})
        # The destination URL must be fully encoded in the output query string.
        query = result.url.split("?", 1)[1]
        assert "dest=https%3A%2F%2Fdestination.example.com" in query
        assert "%" in query


# ---------------------------------------------------------------------------
# Golden test vectors
# ---------------------------------------------------------------------------

_VECTORS_PATH = (
    pathlib.Path(__file__).parent.parent
    / "static"
    / "test-vectors"
    / "universal-macro-translation.json"
)


def _load_vectors() -> list[dict]:
    with _VECTORS_PATH.open() as f:
        data = json.load(f)
    return data["cases"]


@pytest.mark.parametrize("case", _load_vectors(), ids=lambda c: c["id"])
def test_golden_vector(case: dict) -> None:
    """Each case in universal-macro-translation.json must pass."""
    pixel_url: str = case["pixel_url"]
    mapping: dict = case["mapping"]
    expected: dict = case["expected"]

    result = universal_macro_translation(pixel_url, mapping)

    assert result.url == expected["url"], (
        f"[{case['id']}] url mismatch\n"
        f"  got:      {result.url!r}\n"
        f"  expected: {expected['url']!r}"
    )
    assert result.dropped_params == expected["dropped_params"], (
        f"[{case['id']}] dropped_params mismatch\n"
        f"  got:      {result.dropped_params!r}\n"
        f"  expected: {expected['dropped_params']!r}"
    )
    assert result.unmapped_macros == expected["unmapped_macros"], (
        f"[{case['id']}] unmapped_macros mismatch\n"
        f"  got:      {result.unmapped_macros!r}\n"
        f"  expected: {expected['unmapped_macros']!r}"
    )
