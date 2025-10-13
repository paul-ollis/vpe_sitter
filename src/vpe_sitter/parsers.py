"""Lazy loading of different Tree-sitter language parsers."""
from __future__ import annotations

import importlib
from inspect import cleandoc
from pathlib import Path

from tree_sitter import Language, Parser

import vpe
from vpe import vim
from vpe.core import echo_msg, log

# Function to print informational messages.
# echo_msg = partial(echo_msg, soon=True)

_std_filetype_to_parser_module_name: dict[str, str] = {
    'python': 'tree_sitter_python',
    'c': 'tree_sitter_c',
}
_filetype_to_parser_module_name: dict[str, str] = {}
_filetype_to_language: dict[str, Language | None] = {}
_user_provided: set[str] = set()


def _init_parser_tables() -> None:
    """Load the set of supported parsers."""
    _filetype_to_parser_module_name.clear()
    _filetype_to_parser_module_name.update(_std_filetype_to_parser_module_name)
    conf_path = _determine_conf_path()
    if not conf_path.is_file():
        return

    lines = conf_path.read_text(encoding='utf-8').splitlines()
    for i, rawline in enumerate(lines):
        line = rawline.strip()
        if line.startswith('#'):
            continue
        try:
            lang_name, module_name = line.split()
        except ValueError:
            log(f'conf_path[{i+1}]: Syntax error')
            continue
        _filetype_to_parser_module_name[lang_name] = module_name
        _user_provided.add(lang_name)


def provide_parser(filetype: str) -> Parser | None:
    """Provide a new Parser instance for the given filetype.

    :filetype:
        The value of the `filetype` option for the requesting buffer.
    :return:
        A newly created Tree-sitter Parser or ``None`` if the filetype if not
        supported.
    """
    if not _filetype_to_parser_module_name:
        _init_parser_tables()

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


def list_supported_languages(to_log: bool = False) -> None:
    """List the set of supported languages."""
    put = log if to_log else echo_msg

    if not _filetype_to_parser_module_name:
        _init_parser_tables()

    put('Languages configured:')
    for name in sorted(_filetype_to_parser_module_name):
        if name in _user_provided:
            put(f'   {name} (user provided)')
        else:
            put(f'   {name}')
    put('Note: Support depends on correctly installed Tree-sitter code.')
    put('')
    put('Any user configured languages are defined in:')
    put(f'    {_determine_conf_path()}')


def open_config() -> None:
    """Open a buffer contaning the parser configuration file."""
    conf_path = _determine_conf_path(show_errors=True)
    if conf_path is None:
        return
    vpe.commands.edit(f'{conf_path}')
    if not conf_path.exists():
        def add_template_text():
            vim.current.buffer[:] = cleandoc(
                _LANGUAGES_TEMPLATE).splitlines()

        vpe.call_soon(add_template_text)


def _determine_conf_path(show_errors: bool = False) -> Path | None:
    """Work out the path for the configuration file."""
    vimdir: Path = Path(vpe.dot_vim_dir())
    if not vimdir.is_dir():
        # Something wierd is going on.
        if show_errors:
            echo_msg(f'{vimdir} is not a directory!')
            return None

    config_dir = vimdir / 'plugin' / 'vpe_sitter'
    if not config_dir.is_dir():
        try:
            config_dir.mkdir(parents=True)
        except OSError:
            if show_errors:
                echo_msg(
                    f'{config_dir} is not a directory and could not be'
                    ' created!')

    return config_dir / 'languages.conf'


_LANGUAGES_TEMPLATE = '''
# User configured languages.
#
# Each line consists of the language name and the Tree-sitter Python (import)
# module name, separated by one or more spaces. Language names should be lower
# case.
<lang-name> <module_name>
'''
