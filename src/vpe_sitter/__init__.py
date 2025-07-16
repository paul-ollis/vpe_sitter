"""Provide core support for the use of Tree-sitter parse trees.

This plugin maintains a Tree-sitter parse tree for each buffer that
has a supported language.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import vpe
from vpe import core, vim
from vpe.argparse import (
    CommandBase, SubCommandBase, TopLevelSubCommandHandler, command_handler)

from vpe_sitter import listen, parsers

if TYPE_CHECKING:
    from argparse import Namespace


def treesit_current_buffer() -> str:
    """Start running Tree-sitter on the current buffer.

    A `Listener` instance is attached to the buffer's store. The `Listener`
    listens for changes to the buffer's contents and (re)parses the code
    as a result. The parsing executes as a pseudo-background task so that Vim
    remains responsive.

    :return:
        An error message id parsing is not possible. An empty string if
        successful.
    """
    buf = vim.current.buffer
    if vim.options.encoding != 'utf-8':
        # Currently, I think, UTF-8 encoded text is required.
        return f'Cannot run Tree-sitter on {buf.options.encoding} text.'

    filetype = buf.options.filetype
    parser = parsers.provide_parser(filetype)
    if parser is None:
        # No Tree-sitter support available.
        return f'No Tree-sitter parser available for {filetype}.'

    print(f'Can parse {filetype}')
    print(f'   {parser=}')
    print(f'   {parser.language=}')

    store = buf.store('tree-sitter')
    store.listener = listen.Listener(buf, parser)

    st = '%1*%<%5*%n: %f %1* %2*%m%1*%R%=%4*%15'
    st += '{Cur_prop()}'
    st += '%1* %3*%y%1* W=%{winwidth(0)} %8(%lx%c%) %P'
    vim.current.window.options.statusline = st

    return ''


class TreeCommand(CommandBase):
    """The 'debug tree' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.arg_parser.add_argument(
            'start_line', type=int, help='First line of tree dump range.')
        self.arg_parser.add_argument(
            'end_line', type=int, help='Last line of tree dump range.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit debug tree' command."""
        debug = listen.debug_settings
        debug.tree_line_start = args.start_line
        debug.tree_line_end = args.end_line


class RangesCommand(CommandBase):
    """The 'debug ranges' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.arg_parser.add_argument(
            'flag', choices=['on', 'off'],
            help='Enable (on) or disable (off) tree change ranges logging.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit debug ranges' command."""
        debug = listen.debug_settings
        debug.log_changed_ranges = args.flag == 'on'


class BufchangesCommand(CommandBase):
    """The 'debug bufchanges' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.arg_parser.add_argument(
            'flag', choices=['on', 'off'],
            help='Enable (on) or disable (off) buffer changes logging.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit deug bufchanges' command."""
        debug = listen.debug_settings
        debug.log_buffer_changes = args.flag == 'on'


class DebugSubcommand(SubCommandBase):
    """The 'debug' sub-command support."""

    sub_commands = {
        'tree': (TreeCommand, 'Control tree dumping.'),
        'ranges': (RangesCommand, 'Turn changed ranges logging on/off.'),
        'bufchanges': (
            BufchangesCommand, 'Turn buffer change logging on/off.'),
    }


class Plugin(TopLevelSubCommandHandler, core.CommandHandler):
    """The plug-in, which provides the commands."""

    sub_commands = {
        'on': (':simple', 'Turn on tree sitting for the current buffer.'),
        'debug': (DebugSubcommand, 'Control debugging logging.'),
    }

    def __init__(self, command_name: str):
        super().__init__(command_name=command_name)
        self.auto_define_commands()
        self._init_completion()

    @command_handler('Treesit', bar=True)
    def handle_sub_command(self, *cmd_args):
        """Parse and execute a Treesit command."""
        sub_cmd, args = self.sub_command_parser.parse_args(cmd_args)
        if sub_cmd == '':
            return
        super().handle_sub_command(sub_cmd, args)

    def handle_on(self) -> None:
        """Handle the 'Treesit on' command."""
        treesit_current_buffer()

    # TODO: A non-command.
    @vpe.CommandHandler.command('Ashow', pass_info=True, range=True)
    def ashow(self, info: vpe.CommandInfo):
        """Execute the Ashow command."""
        buf = vim.current.buffer
        highlighter = buf.store('tree-sitter').highlighter
        highlighter.log_range = range(info.line1 - 1, info.line2)
        highlighter.dry_run = True
        try:
            highlighter.apply_props(range(0, len(buf)))
        finally:
            highlighter.log_range = None
            highlighter.dry_run = False

    # TODO: A non-command.
    @vpe.CommandHandler.command('Ainfo', pass_info=True)
    def ainfo(self, _info: vpe.CommandInfo):
        """Execute the Ainfo command."""
        buf = vim.current.buffer
        lnum, _ = vim.current.window.cursor
        highlighter = buf.store('tree-sitter').highlighter
        highlighter.identify_line(lnum - 1)


app = Plugin('Treesit')

_CUR_PROP = """
function! Cur_prop()
    let props = prop_list(line('.'))
    let col = col('.')
    let found = []
    for prop in props
        let pcol = prop['col']
        let plen = prop['length']
        if pcol <= col && (pcol + plen) > col
            call add(found, get(prop, 'type', '-'))
        endif
    endfor
    return found
endfunction
"""

vim.command(_CUR_PROP)
