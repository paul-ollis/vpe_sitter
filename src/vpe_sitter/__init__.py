"""Provide core support for the use of Tree-sitter parse trees.

This plugin maintains a Tree-sitter parse tree for each buffer that
has a supported language.
"""
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import vpe
from vpe import core, vim
from vpe.argparse import (
    CommandBase, SubCommandBase, TopLevelSubCommandHandler)

from vpe_sitter import listen, parsers

if TYPE_CHECKING:
    from argparse import Namespace

# Function to print informational messages.
echo_msg = partial(core.echo_msg, soon=True)


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

    store = buf.retrieve_store('tree-sitter')
    if store is None:
        print(f'Can parse {filetype}')
        print(f'   {parser=}')
        print(f'   {parser.language=}')
        store = buf.store('tree-sitter')
        store.listener = listen.Listener(buf, parser)

    return ''


class TreeCommand(CommandBase):
    """The 'debug tree' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
            'start_line', type=int, help='First line of tree dump range.')
        self.parser.add_argument(
            'end_line', type=int, help='Last line of tree dump range.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit debug tree' command."""
        print("HANDLE TREE", args)
        debug = listen.debug_settings
        debug.tree_line_start = args.start_line
        debug.tree_line_end = args.end_line


class RangesCommand(CommandBase):
    """The 'debug ranges' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
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
        self.parser.add_argument(
            'flag', choices=['on', 'off'],
            help='Enable (on) or disable (off) buffer changes logging.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit debug bufchanges' command."""
        debug = listen.debug_settings
        debug.log_buffer_changes = args.flag == 'on'


class PerformanceCommand(CommandBase):
    """The 'debug performance' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
            'flag', choices=['on', 'off'],
            help='Enable (on) or disable (off) buffer changes logging.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit debug performance' command."""
        debug = listen.debug_settings
        debug.log_performance = args.flag == 'on'


class DebugSubcommand(SubCommandBase):
    """The 'debug' sub-command support."""

    sub_commands = {
        'thisline': (':simple', 'Log partial tree for this line.'),
        'status': (':simple', 'Display current debug settings.'),
        'tree': (TreeCommand, 'Control tree dumping.'),
        'ranges': (RangesCommand, 'Turn changed ranges logging on/off.'),
        'bufchanges': (
            BufchangesCommand, 'Turn buffer change logging on/off.'),
        'performance': (
            PerformanceCommand, 'Turn performance logging on/off.'),
    }

    def handle_thisline(self) -> None:
        """Print partial tree showing the current line."""
        buf = vim.current.buffer
        if store := buf.retrieve_store('tree-sitter'):
            vim.command('Vpe log show')
            row, _ = vim.current.window.cursor
            print("HI")
            store.listener.print_tree(row, row)
            print("--")
        else:
            echo_msg('Tree-sitter is not enabled for this buffer')

    def handle_status(self) -> None:
        """Print the current debug settings."""
        s = []
        debug = listen.debug_settings
        s.append('VPE-sitter status:')
        s.append(f'    Log buffer changes:   {debug.log_buffer_changes}')
        s.append(f'    Log changed ranges:   {debug.log_changed_ranges}')
        s.append(f'    Tree dump line range: {debug.tree_line_start}'
                 f' - {debug.tree_line_end}')
        print('\n'.join(s))


class PauseCommand(CommandBase):
    """The 'pause' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
            'flag', choices=['on', 'off'],
            help='Pause (on) or resume (off) active sitting.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit pause' command."""
        buf = vim.current.buffer
        if store := buf.retrieve_store('tree-sitter'):
            store.listener.pause(args.flag == 'on')


class Plugin(TopLevelSubCommandHandler):
    """The plug-in, which provides the commands."""

    sub_commands = {
        'on': (':simple', 'Turn on tree sitting for the current buffer.'),
        'debug': (DebugSubcommand, 'Control debugging logging.'),
        'pause': (PauseCommand, 'Pause automatic parsing (for debug use).'),
    }

    def handle_on(self) -> None:
        """Handle the 'Treesit on' command."""
        treesit_current_buffer()


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
