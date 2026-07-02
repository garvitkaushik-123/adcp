# Paste this block into src/adcp/__init__.py after the registry_sync import block:
#
# from adcp.substitution import (
#     MacroEntry,
#     MacroMapping,
#     MacroTranslationResult,
#     NativeEntry,
#     ValueEntry,
#     encode_unreserved,
#     universal_macro_translation,
# )
#
# And add these to the __all__ list at the end of the file:
#     "MacroEntry",
#     "MacroMapping",
#     "MacroTranslationResult",
#     "NativeEntry",
#     "ValueEntry",
#     "encode_unreserved",
#     "universal_macro_translation",
