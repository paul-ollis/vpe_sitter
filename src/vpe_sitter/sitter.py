"""Tree-sitter specific support."""

import json
from pathlib import Path
from tree_sitter import Language

from vpe.core import log

ts_dir = Path('/home/paul/np/os/tree-sitter')
ts_parsers_dir = ts_dir / 'parsers'


def init_language(lang_name: str, source_name: str) -> Language:
    """Perform any language specific initialisation.

    :lang_name:   The name of the language as known by the parser.
    :source_name: The name of the language within the parser's source tree.
                  This is often the same as lang_name.
    """
    ts_lib = ts_parsers_dir / f'build/sitter-{lang_name}.so'
    Language.build_library(
        str(ts_lib), [str(ts_parsers_dir / f'tree-sitter-{source_name}')])
    return Language(str(ts_lib), lang_name)


def dump_node_names(lang: str):
    """Dump a list of the node names defined for a language."""
    nt_path = ts_parsers_dir / f'tree-sitter-{lang}' / 'src/node-types.json'
    nt = json.loads(nt_path.read_text())

    names = set()
    for entry in nt:
        gen_name = entry.get('type')
        if gen_name is None:
            continue
        if not gen_name.startswith('_'):
            names.add(gen_name)

        sub_enties = entry.get('subtypes', [])
        for sub_entry in sub_enties:
            name = sub_entry.get('type')
            if name is None or gen_name.startswith('_'):
                continue
            names.add(name)

    for name in sorted(names):
        log(name)


if __name__ == '__main__':
    name = 'latex'
    init_language(name, name)
    dump_node_names(name)
