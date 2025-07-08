"""Lazy loading of different Tree-sitter language parsers."""
from __future__ import annotations

import importlib
from pathlib import Path

from tree_sitter import Language, Parser, Query

_filetype_to_parser_module_name: dict[str, str] = {
    'python': 'tree_sitter_python',
}
_filetype_to_language: dict[str, Language] = {}


def provide_parser(filetype: str) -> Parser | None:
    """Provide a new Parser instance for the given filetype.

    :filetype:
        The value of the `filetype` option for the requesting buffer.
    :return:
        A newly created Tree-sitter Parser or ``None`` if the filetype if not
        supported.
    """
    if filetype not in _filetype_to_language:
        if filetype not in _filetype_to_parser_module_name:
            print(f'No support registered for {filetype=}')
            _filetype_to_language[filetype] = None
            return None

        module_name = _filetype_to_parser_module_name[filetype]
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            print(f'Failed to import {module_name}: {e}')
            _filetype_to_language[filetype] = None
            return None

        try:
            lang_obj = module.language()
        except Exception as e:
            print(f'Failed to get language from {module_name}: {e}')
            _filetype_to_language[filetype] = None
            return None
        else:
            language = Language(lang_obj)
            _filetype_to_language[filetype] = language

        print(f'Tree-sitter support for {filetype=} is available')

    return Parser(_filetype_to_language[filetype])


# TODO: This should be dead.
def provide_query_for_language(filetype: str) -> Query | None:
    """Parse the S-expressions into a Query for the given language.

    The call **must** only invoke this after `provide_parser` has worked for
    the same filetype.
    """
    mod_path = Path(__file__)
    scmdir_path = mod_path.parent / 'resources/tree_sitter_queries'
    s_file_path = scmdir_path / f'{filetype}.scm'
    if not s_file_path.exists():
        print(f'Tree-sitter S-expr (scm) file not found for {filetype=}')
        print(f'...Looked for in {scmdir_path}')
        return None

    language = _filetype_to_language[filetype]
    return language.query(
        s_file_path.read_text(encoding='utf-8', errors='ignore'))
