"""Support for specific types of files.

There is an simple one-to-one correspondence between the modules in this
package and the values that the Vim :vim:`filetype` option can take.

Since this package can potentially become **very** large, the sub-modules are
programatically imported by the `init` function.
"""

import importlib
from typing import Dict, NamedTuple
from types import ModuleType

from tree_sitter import Parser

from vpe_sitter import sitter


class LangInfo(NamedTuple):
    """Language specific information."""
    parser: Parser
    mod: ModuleType


def init(typename: str):
    """Perform the necessary initialisation for a given type of file.

    This uses cached information if the type of file has already been
    initialised.
    """
    if typename not in info:
        mod = importlib.import_module(f'.{typename}', __package__)
        language = sitter.init_language(mod.lang_name, mod.source_name)
        parser = Parser()
        parser.set_language(language)
        info[typename] = LangInfo(parser, mod)

    return info[typename]


info: Dict[str, LangInfo] = {}
