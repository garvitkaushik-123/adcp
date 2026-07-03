"""One-shot patcher: adds adcp.substitution exports to src/adcp/__init__.py.

Run from the root of the adcp-client-python repo:
    python3 files/patch_init.py   # or wherever you downloaded it
"""
import pathlib, sys

src = pathlib.Path('src/adcp/__init__.py')
if not src.exists():
    sys.exit('Run this from the root of adcp-client-python')

code = src.read_text()

IMPORT_MARKER = 'from adcp.registry_sync import (\n    ChangeHandler,\n    CursorStore,\n    FileCursorStore,\n    RegistrySync,\n)\n'
IMPORT_INSERT = IMPORT_MARKER + ('from adcp.substitution import (\n'
    '    MacroEntry,\n'
    '    MacroMapping,\n'
    '    MacroTranslationResult,\n'
    '    NativeEntry,\n'
    '    ValueEntry,\n'
    '    encode_unreserved,\n'
    '    universal_macro_translation,\n'
    ')\n')

ALL_MARKER = '    # Backward compat: types removed from upstream schemas\n]'
ALL_INSERT = ('    # Backward compat: types removed from upstream schemas\n'
    '    # substitution helpers\n'
    '    "MacroEntry",\n'
    '    "MacroMapping",\n'
    '    "MacroTranslationResult",\n'
    '    "NativeEntry",\n'
    '    "ValueEntry",\n'
    '    "encode_unreserved",\n'
    '    "universal_macro_translation",\n'
    ']')

if 'from adcp.substitution import' in code:
    print('Already patched — nothing to do.')
    sys.exit(0)

if IMPORT_MARKER not in code:
    sys.exit('ERROR: expected registry_sync import block not found; is this the right file?')
if ALL_MARKER not in code:
    sys.exit('ERROR: expected __all__ tail not found.')

code = code.replace(IMPORT_MARKER, IMPORT_INSERT, 1)
code = code.replace(ALL_MARKER, ALL_INSERT, 1)
src.write_text(code)
print('Patched src/adcp/__init__.py')
