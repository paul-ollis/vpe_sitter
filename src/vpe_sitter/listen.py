"""Support for 'listening' for buffer changes and updating syntax information.

This is the back bone of the Aware framework.
"""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from itertools import accumulate
from typing import Callable, NamedTuple, TypeAlias
from weakref import proxy

from tree_sitter import Parser, Tree

import vpe
from vpe.vpe_lib import diffs

#: A list of line ranges that need updating for the latest (re)parsing.
AffectedLines: TypeAlias = list[tuple[int, int]]

#: A callback function for when a (re)parsing completes.
ParseCompleteCallback: TypeAlias = Callable[[AffectedLines], None]

log = functools.partial(vpe.call_soon, print)


class Point(NamedTuple):
    """A zero-based (row, column) point as used by Tree-sitter.

    Note that the column_index is a *byte* offset.
    """

    row_index: int
    column_index: int


class SyntaxTreeEdit(NamedTuple):
    """Details of a tree-sitter syntax tree edit operation."""

    start_byte: int
    old_end_byte: int
    new_end_byte: int
    start_point: Point
    old_end_point: Point
    new_end_point: Point


@dataclass
class InprogressParseOperation:
    """Data capturing a parsing operation that may be partially complete.

    @listener:
        The parent `Listener`.
    @parser:
        The Tree-sitter `Parser` user to (re)parse.
    @code_bytes:
        The code being parsed as a bytes sequence.
    @lines:
        The code being parsed as a list of strings.
    @active:
        This is set ``True`` while parsing is in progress.
    @pending_changes:
        A list of pending changes that must be applied to the `tree` before
        the next parsing run can be started.
    @tree:
        The tree resulting from the last (re)parsing run. Initially ``None``.
    @timer:
        A `vpe.Timer` use to continue a long parse operation.
    @parse_done_callback:
        A function to be invoked when a (re)parsing has completed.
    """
    # pylint: disable=too-many-instance-attributes
    listener: Listener
    parser: Parser
    parse_done_callback: ParseCompleteCallback
    code_bytes: bytes = b''
    lines: list[str] = field(default_factory=list)
    active: bool = False
    pending_changes: list[SyntaxTreeEdit] = field(default_factory=list)
    tree: Tree | None = None
    timer: vpe.Timer | None = None
    changed_ranges: list = field(default_factory=list)

    parse_timeouts: int = 0
    start_time: float = 0.0

    def start(self) -> None:
        """Start a new parsing operation."""
        if self.active:
            return

        a = time.time()
        if self.pending_changes:
            if self.tree is not None:
                for edit in self.pending_changes:
                    self.tree.edit(**edit._asdict())
            self.pending_changes[:] = []
        delta = time.time() - a
        print(f'Pending changes applied in {delta:.4f}s')

        self.active = True
        self.lines = list(self.listener.buf)
        self.code_bytes = '\n'.join(self.lines).encode('utf-8')
        self.start_time = time.time()
        self.parse_timeouts = 0
        self._try_parse()

    def add_edit(self, edit: SyntaxTreeEdit) -> None:
        """Add a pending tree edit to the backlog of edits.

        If no parse run is currently in progress, one is triggered. Otherwise
        a new run will be triggered when the current one finishes.
        """
        self.pending_changes.append(edit)
        vpe.call_soon(self.start)

    def _try_parse(self, _timer: vpe.Timer | None = None) -> None:
        try:
            self.parser.timeout_micros = 5_000
            if self.tree is not None:
                tree = self.parser.parse(
                    self.code_bytes, old_tree=self.tree, encoding='utf-8')
            else:
                tree = self.parser.parse(self.code_bytes, encoding='utf-8')
        except ValueError:
            # The only known cause is a timeout.
            self._schedule_reparse()
            self.parse_timeouts += 1
        else:
            # TODO:
            #   Figure out if the changed ranges are actually useful. So far,
            #   my investigations suggest that the Python binding do not return
            #   a useful set of differences.
            if self.tree:
                changed_ranges = [
                    (r.start_point.row, r.end_point.row)
                    for r in self.tree.changed_ranges(tree)
                ]
                s = [f'Changes: {type(changed_ranges)}']
                for r in changed_ranges:
                    s.append(f'    {r}')
                for r in self.tree.changed_ranges(tree):
                    s.append(f'    {r}')
                print('\n'.join(s))
            else:
                changed_ranges = []
            self.tree = tree
            #-self.dump()
            self.active = False
            if self.timer:
                self.timer = None
            delta = time.time() - self.start_time
            print(
                f'Parse completed in {delta:.4f}s,'
                f' after {self.parse_timeouts} timeouts'
            )
            self.parse_done_callback(changed_ranges)

            if self.pending_changes:
                vpe.call_soon(self.start)

    def _schedule_reparse(self) -> None:
        ms_delay = 10
        self.timer = vpe.Timer(ms_delay, self._try_parse)

    def dump(self):
        """Dump a printout of the tree."""
        if self.tree is None:
            return

        # I am not sure what the grammar name represents, nor how it can be
        # used. So I ignore it.
        show_grammar_name = False
        lines_left = 50

        def put_node(node, field_name=''):
            nonlocal lines_left

            if lines_left <= 0:
                if lines_left == 0:
                    s.append(f'{pad[-1]}...')
                lines_left -= 1
                return

            a = tuple(node.start_point)
            b = tuple(node.end_point)
            type_name = node.type

            if show_grammar_name:
                grammar_name = node.grammar_name
                if grammar_name and grammar_name != type_name:
                    name = f'{grammar_name}:{type_name}'
                else:
                    name = type_name
            name = type_name

            if field_name:
                name = f'{field_name}:{name}'
            s.append(f'{pad[-1]}{name} {a}->{b}')
            lines_left -= 1

            pad.append(pad[-1] + '  ')
            for i, child in enumerate(node.children):
                field_name = node.field_name_for_child(i)
                put_node(child, field_name)
            pad.pop()

        s = []
        pad = ['']
        put_node(self.tree.root_node)
        print('\n'.join(s))


class Listener:
    """Per-buffer handler that uses buffer changes to run Tree-sitter.

    @buf:
        The buffer being monitored for changes.
    @parser:
        The Tree-sitter `Parser` user to (re)parse.
    @parse_complete_callbacks:
        A list of functions to be invoked whenever a (re)parsing comppletes.
    @in_progress_parse_operation:
        A `InprogressParseOperation` object that runs parse operations as
        a "background" operation.
    @byte_offsets:
        The byte offsets for the start of each line in the buffer.
    @listen_handle:
        The Vim provided handle for the registered buffer listener.
    """
    # pylint: disable=too-many-instance-attributes
    listen_handle: vpe.BufListener
    in_progress_parse_operation: InprogressParseOperation

    def __init__(self, buf: vpe.Buffer, parser: Parser):
        self.buf = buf
        self.parser: Parser = parser
        self.parse_complete_callbacks: list[ParseCompleteCallback] = []
        self.in_progress_parse_operation = InprogressParseOperation(
            proxy(self), self.parser, self.handle_parse_complete)

        # The use of Vim's line2byte function seems like a good way to get the
        # byte offsets of the lines, but this way is about 10 times faster.
        self.byte_offsets = list(accumulate([
            len(line.encode('utf-8')) + 1 for line in self.buf], initial=0))

        self.listen_handle = buf.add_listener(self.handle_changes)
        self.in_progress_parse_operation.start()

    @property
    def tree(self) -> Tree:
        """The tree resulting from the most recent parse operation."""
        return self.in_progress_parse_operation.tree

    def handle_parse_complete(self, affected_lines: AffectedLines) -> None:
        """Update information following a (re)parse of the buffer's code."""
        for callback in self.parse_complete_callbacks:
            callback(affected_lines)

    def handle_changes(
            self,
            _buf: vpe.Buffer,
            start_lidx: int,
            end_lidx: int,
            added:int,
            ops: list[diffs.Operation],
        ) -> None:
        """Process changes for the associated buffer.

        :_buf:       The affected buffer, ignored because the buffer is known.
        :start_lidx: Start of affected line range.
        :end_lidx:   End of affected line range.
        :added:      The number of lines added or, if negative, deleted.
        :ops:        A list of the operations applied within the line range.
        """
        #- log(f'Change: {start_lidx=} {end_lidx=} {added=}')
        # TODO: Protect against IndexError.

        # The start and old end byte offsets depend on the previously
        # calculated line byte offsets.
        start_byte = self.byte_offsets[start_lidx]
        old_end_byte = self.byte_offsets[end_lidx]

        # The line byte offsets need to be updated based on the new buffer
        # contents.
        start_offset = self.byte_offsets[start_lidx]
        self.byte_offsets[start_lidx:] = list(accumulate(
            [len(line.encode('utf-8')) + 1 for line in self.buf[start_lidx:]],
            initial=start_offset)
        )

        # The new end byte offset uses the newly calculated line byte offsets.
        new_end_byte = self.byte_offsets[end_lidx + added]

        # The start, old and new end points are more simply generated.
        start_point = Point(start_lidx, 0)
        old_end_point = Point(end_lidx, 0)
        new_end_point = Point(end_lidx + added, 0)

        edit = SyntaxTreeEdit(
            start_byte, old_end_byte, new_end_byte,
            start_point, old_end_point, new_end_point,
        )
        self.in_progress_parse_operation.add_edit(edit)

    def add_parse_complete_callback(
            self, callback: ParseCompleteCallback,
        ) -> None:
        """Add a callback for code parsing completion."""
        self.parse_complete_callbacks.append(callback)
        active = self.in_progress_parse_operation.active
        tree = self.in_progress_parse_operation.tree
        if tree is not None and not active:
            callback([])
