"""Provide core support for the use of Tree-sitter parse trees.

This plugin maintains a Tree-sitter parse tree for each buffer that
has a supported language.
"""
from __future__ import annotations

import platform
import sys
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import vpe
from vpe import core, vim
from vpe.core import log
from vpe.user_commands import (
    CommandHandler, SubcommandHandlerBase, TopLevelSubcommandHandler)

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
        An error message if parsing is not possible. An empty string if
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
        log(f'VPE-sitter: Can parse {filetype}')
        log(f'VPE-sitter:    {parser=}')
        log(f'VPE-sitter:    {parser.language=}')
        store = buf.store('tree-sitter')
        store.listener = listen.Listener(buf, parser)

    return ''


class TreeCommand(CommandHandler):
    """The 'debug tree' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
            'start_line', type=int, help='First line of tree dump range.')
        self.parser.add_argument(
            'end_line', type=int, help='Last line of tree dump range.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit debug tree' command."""
        debug = listen.debug_settings
        debug.tree_line_start = args.start_line
        debug.tree_line_end = args.end_line


class RangesCommand(CommandHandler):
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


class BufchangesCommand(CommandHandler):
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


class PerformanceCommand(CommandHandler):
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


class DebugAllCommand(CommandHandler):
    """The 'debug all' sub-command support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
            'flag', choices=['on', 'off'],
            help='Enable (on) or disable (off) all logging.')

    def handle_command(self, args: Namespace):
        """Handle the 'Treesit debug performance' command."""
        listen.debug_settings.set_all(args.flag == 'on')


class LogTreeSubcommand(CommandHandler):
    """The 'log tree' subcommand support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
            '--all', action='store_true',
            help='Log the entire parse tree.')
        self.parser.add_argument(
            '--start', type=int, default=0,
            help='First line to include in the parse tree output.')
        self.parser.add_argument(
            '--end', type=int, default=0,
            help='Last line to include in the parse tree output.')
        self.parser.add_argument(
            '--ranges', action='store_true',
            help='Include line/column ranges for each node.')

    def handle_command(self, args: Namespace) -> None:
        """Handle the log tree subcommand."""
        buf = vim.current.buffer
        if not (store := buf.retrieve_store('tree-sitter')):
            echo_msg('Tree-sitter is not enabled for this buffer')
            return

        vim.command('Vpe log show')
        if args.all:
            store.listener.print_tree(-2, -1, ranges=args.show_ranges)
        elif args.start > 0 and args.end >= args.start:
            store.listener.print_tree(
                args.start, args.end, show_ranges=args.ranges)
        elif args.start > 0:
            store.listener.print_tree(
                args.start, args.start, show_ranges=args.ranges)
        else:
            row, _ = vim.current.window.cursor
            store.listener.print_tree(row, row, show_ranges=args.ranges)


class LogSubcommand(SubcommandHandlerBase):
    """The 'log' sub-command support."""

    subcommands = {
        'tree': (LogTreeSubcommand, 'Log tree information.'),
    }


class DebugSubcommand(SubcommandHandlerBase):
    """The 'debug' subcommand support."""

    subcommands = {
        'all': (
            DebugAllCommand, 'Turn all logging on/off.'),
        'ranges': (RangesCommand, 'Turn changed ranges logging on/off.'),
        'bufchanges': (
            BufchangesCommand, 'Turn buffer change logging on/off.'),
        'performance': (
            PerformanceCommand, 'Turn performance logging on/off.'),
        'status': (':simple', 'Display current debug settings.'),
        'tree': (TreeCommand, 'Control tree dumping.'),
        'fail': (':simple', 'Simulate change tracking failure - do not use!'),
    }

    def handle_status(self, _args: Namespace) -> None:
        """Print the current debug settings."""
        s = []
        debug = listen.debug_settings
        s.append('VPE-sitter status:')
        s.append(f'    Log performance:      {debug.log_performance}')
        s.append(f'    Log bufchanges:       {debug.log_buffer_changes}')
        s.append(f'    Log ranges:           {debug.log_changed_ranges}')
        s.append(f'    Tree dump line range: {debug.tree_line_start}'
                 f' --> {debug.tree_line_end}')
        log('\n'.join(s))

    def handle_fail(self, _args: Namespace) -> None:
        """Simulate a failue of change tracking for the current buffer."""
        buf = vim.current.buffer
        if store := buf.retrieve_store('tree-sitter'):
            print("Doing it!")
            store.listener.simulate_failure = True
        else:
            print("Wrong buffer")


class InstallHintCommand(CommandHandler):
    """The 'hint install' subcommand support."""

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
            'package',
            help='The name of your python package.')

    def handle_command(self, args: Namespace):
        """Handle the 'Tree hint install' command."""
        vimdir: Path = Path(vpe.dot_vim_dir())
        venvdir = vimdir / 'lib' / 'python'
        py_prog = venvdir / 'bin' / 'python'
        cmd = ''
        if py_prog.exists():
            cmd = f'{py_prog} -m pip install --upgrade {args.package}'
        else:
            if platform.system() == 'Windows':
                # I do not know why, but on Windows sys.executable is the GVIM
                # program! So we build the name using sys.exec_prefix.
                dirpath = Path(sys.exec_prefix)
                py_prog = dirpath / 'python.exe'
            else:
                py_prog = sys.executable
            if py_prog.exists():
                cmd = f'{py_prog} -m pip install --user --upgrade'
                cmd += f' {args.package}'
        if cmd:
            echo_msg('Suggested install command is:')
            echo_msg(f'    {cmd}')
        else:
            echo_msg('Could not determine the Python executable!')


class HintSubcommand(SubcommandHandlerBase):
    """The 'hint' subcommand support."""

    subcommands = {
        'install': (InstallHintCommand, 'Hinting for installation.'),
    }


class InfoSubcommand(SubcommandHandlerBase):
    """The 'info' subcommand support."""

    subcommands = {
        'languages': (':simple', 'List supported languages.'),
    }

    def add_arguments(self) -> None:
        """Add the arguments for this command."""
        self.parser.add_argument(
            '--log', action='store_true',
            help='Write output to the VPE log.')

    def handle_languages(self, args: Namespace) -> None:
        """Handle the 'Treesit info languages command."""
        parsers.list_supported_languages(args.log)


class PauseCommand(CommandHandler):
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


class Plugin(TopLevelSubcommandHandler):
    """The plug-in, which provides the commands."""

    subcommands = {
        'on': (':simple', 'Turn on tree sitting for the current buffer.'),
        'openconfig': (':simple', 'Open the user configuration file.'),
        'debug': (DebugSubcommand, 'Control debugging logging.'),
        'pause': (PauseCommand, 'Pause automatic parsing (for debug use).'),
        'log': (LogSubcommand, 'Write information to the VPE log.'),
        'hint': (
            HintSubcommand, 'Provide hints for things like installation.'),
        'info': (InfoSubcommand, 'Display useful information.'),
    }

    def handle_on(self, _args: Namespace) -> None:
        """Handle the 'Treesit on' command."""
        treesit_current_buffer()

    def handle_openconfig(self, _args: Namespace) -> None:
        """Handle the 'Treesit openconfig' command."""
        parsers.open_config()


app = Plugin('Treesit')
