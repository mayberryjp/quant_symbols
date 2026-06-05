"""Repository-root CLI package for quant_symbols.

The runtime package lives under ``src/quant_symbols``. Keeping this path bridge
lets ``python3 -m quant_symbols.cli`` work from a repository checkout during
local smoke checks.
"""

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

_src_package = Path(__file__).resolve().parent.parent / "src" / "quant_symbols"
if _src_package.exists():
    __path__.append(str(_src_package))
