"""Pixel URL macro substitution helpers for AdCP buyers.

Two public functions:

* :func:`encode_unreserved` — RFC-3986 unreserved-charset encoder. Callers
  that embed dynamic data as pixel URL query-parameter values MUST pass each
  value through this before building the URL. The unreserved set is
  ``ALPHA / DIGIT / "-" / "." / "_" / "~"`` (RFC 3986 §2.3); every other
  byte is percent-encoded as uppercase ``%NN``.

* :func:`universal_macro_translation` — single-pass substitution of
  ``${MACRO_NAME}`` placeholders in a pixel URL. Mirrors the JS SDK's
  ``substitution/translate.ts`` behaviour so buyers can share golden test
  vectors across language SDKs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TypedDict
from urllib.parse import unquote as _unquote, urlsplit, urlunsplit

from adcp.types._generated import UniversalMacro


# ---------------------------------------------------------------------------
# RFC-3986 unreserved-charset encoder
# ---------------------------------------------------------------------------

# RFC 3986 §2.3: unreserved = ALPHA / DIGIT / "-" / "." / "_" / "~"
_RFC3986_UNRESERVED: frozenset[int] = frozenset(
    b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
)


def encode_unreserved(raw: str) -> str:
    """Percent-encode all bytes outside the RFC-3986 unreserved set.

    The unreserved set is ``ALPHA / DIGIT / "-" / "." / "_" / "~"``
    (RFC 3986 §2.3). Every other byte in the UTF-8 encoding of *raw* is
    emitted as uppercase ``%NN``.

    This differs from :func:`urllib.parse.quote` with its default
    ``safe='/'``: the stdlib function leaves ``/``, ``@``, ``:``, and other
    sub-delimiters unencoded, which is unsafe when the encoded value will
    occupy a query-parameter value slot.

    Args:
        raw: The string to encode.

    Returns:
        The percent-encoded string containing only unreserved characters
        and uppercase ``%NN`` escape sequences.
    """
    parts: list[str] = []
    for byte in raw.encode('utf-8'):
        if byte in _RFC3986_UNRESERVED:
            parts.append(chr(byte))
        else:
            parts.append(f'%{byte:02X}')
    return ''.join(parts)


# ---------------------------------------------------------------------------
# Universal macro substitution
# ---------------------------------------------------------------------------

# The entire parameter value must be ${MACRO_NAME}.
# Partial macros such as "prefix_${MACRO}" are treated as literals.
_MACRO_RE: re.Pattern[str] = re.compile(r'^\$\{([A-Z0-9_]+)\}$')


class ValueEntry(TypedDict):
    """Macro resolved to a plain value — encoded with :func:`encode_unreserved`."""

    value: str


class NativeEntry(TypedDict):
    """Macro resolved to a pre-encoded native token — inserted verbatim."""

    native: str


MacroEntry = ValueEntry | NativeEntry
MacroMapping = dict[str | UniversalMacro, MacroEntry]


@dataclass
class MacroTranslationResult:
    """Result of :func:`universal_macro_translation`.

    Attributes:
        url: The pixel URL after substitution.  Parameters whose macro
            placeholder was found in *mapping* carry the substituted value;
            parameters with no macro are unchanged; parameters whose macro
            was absent from *mapping* are omitted.
        dropped_params: Names of query parameters omitted because their
            ``${MACRO_NAME}`` placeholder was not present in *mapping*.
        unmapped_macros: Deduplicated macro names that appeared in the URL
            but were absent from *mapping*.  Each name appears at most once
            even if multiple parameters reference the same macro.
    """

    url: str
    dropped_params: list[str] = field(default_factory=list)
    unmapped_macros: list[str] = field(default_factory=list)


def universal_macro_translation(
    pixel_url: str,
    mapping: MacroMapping,
) -> MacroTranslationResult:
    """Substitute ``${MACRO_NAME}`` placeholders in a pixel URL.

    Single-pass substitution: each query-parameter value is inspected once
    for a ``${MACRO_NAME}`` placeholder that spans the *entire* value.
    Partial macros (e.g. ``prefix_${MACRO}``) are left untouched as literals.

    Substitution semantics per *mapping* entry type:

    * ``{"value": v}`` — *v* is encoded with :func:`encode_unreserved` and
      used as the parameter value.
    * ``{"native": t}`` — *t* is inserted verbatim.  Use for ad-server
      tokens that must remain intact and will be filled downstream
      (e.g. ``${CLICK_URL}`` forwarded to a redirect chain).

    If a placeholder macro is absent from *mapping* the parameter is dropped
    and the macro name is recorded in
    :attr:`MacroTranslationResult.unmapped_macros`.  Parameters with no
    macro placeholder are passed through unchanged.

    Because :class:`~adcp.types.UniversalMacro` is a :class:`~enum.StrEnum`,
    mapping keys may be either enum members or plain strings — both resolve
    identically via hash equality.

    Args:
        pixel_url: Raw pixel URL, possibly containing ``${MACRO}``
            query-parameter values.
        mapping: Macro-name → entry dict.

    Returns:
        A :class:`MacroTranslationResult` with the translated URL and
        bookkeeping lists.
    """
    split = urlsplit(pixel_url)

    if not split.query:
        return MacroTranslationResult(url=pixel_url)

    out_parts: list[str] = []
    dropped_params: list[str] = []
    unmapped_macros: list[str] = []

    for raw_pair in split.query.split('&'):
        eq_pos = raw_pair.find('=')
        if eq_pos < 0:
            # Key-only parameter — pass through unchanged.
            out_parts.append(raw_pair)
            continue

        raw_name = raw_pair[:eq_pos]
        raw_value = raw_pair[eq_pos + 1:]

        m = _MACRO_RE.match(raw_value)
        if m is None:
            # Not a bare macro — pass through unchanged.
            out_parts.append(raw_pair)
            continue

        macro_name = m.group(1)
        # UniversalMacro is StrEnum so dict lookup works with plain strings.
        entry: MacroEntry | None = mapping.get(macro_name)  # type: ignore[arg-type]

        if entry is None:
            dropped_params.append(_unquote(raw_name))
            if macro_name not in unmapped_macros:
                unmapped_macros.append(macro_name)
            continue

        if 'value' in entry:
            encoded = encode_unreserved(entry['value'])  # type: ignore[typeddict-item]
            out_parts.append(f'{raw_name}={encoded}')
        else:
            out_parts.append(f'{raw_name}={entry["native"]}')  # type: ignore[typeddict-item]

    new_query = '&'.join(out_parts)
    new_url = urlunsplit((split.scheme, split.netloc, split.path, new_query, split.fragment))

    return MacroTranslationResult(
        url=new_url,
        dropped_params=dropped_params,
        unmapped_macros=unmapped_macros,
    )


__all__ = [
    'MacroEntry',
    'MacroMapping',
    'MacroTranslationResult',
    'NativeEntry',
    'ValueEntry',
    'encode_unreserved',
    'universal_macro_translation',
]
