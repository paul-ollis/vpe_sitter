"""Lazy loading of different Tree-sitter language parsers."""
from __future__ import annotations

import importlib

from tree_sitter import Language, Parser

from vpe.core import log

_filetype_to_parser_module_name: dict[str, str] = {
    'python': 'tree_sitter_python',
    'c': 'tree_sitter_c',
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
            log(f'No support registered for {filetype=}')
            _filetype_to_language[filetype] = None
            return None

        module_name = _filetype_to_parser_module_name[filetype]
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            log(f'Failed to import {module_name}: {e}')
            _filetype_to_language[filetype] = None
            return None

        try:
            lang_obj = module.language()
        except Exception as e:
            log(f'Failed to get language from {module_name}: {e}')
            _filetype_to_language[filetype] = None
            return None
        else:
            language = Language(lang_obj)
            _filetype_to_language[filetype] = language

        log(f'Tree-sitter support for {filetype=} is available')

    language = _filetype_to_language[filetype]
    if language is None:
        return None
    else:
        return Parser(language)
