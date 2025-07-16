"""Support for 'listening' for buffer changes and updating syntax information.

This provides the `Listen` class, which can be attached to a buffer. It listens
for buffer changes and parses the contents in response.
"""
from __future__ import annotations

import functools
import time
from enum import Enum
from dataclasses import dataclass, field
from itertools import accumulate
from typing import Callable, NamedTuple, TypeAlias
from weakref import proxy

from tree_sitter import Parser, Tree

import vpe
from vpe.vpe_lib import diffs

#: A list of line ranges that need updating for the latest (re)parsing.
AffectedLines: TypeAlias = list[range] | None

#: A callback function for when a (re)parsing completes.
ParseCompleteCallback: TypeAlias = Callable[
    ['ConditionCode', AffectedLines], None]

#: How long the parse tree may be 'unclean' before clients are notified.
MAX_UNCLEAN_TIME = 0.5

#: A print-equivalent function that works inside Vim callbacks.
log = functools.partial(vpe.call_soon, print)


@dataclass
class DebugSettings:
    """Setting controlling debug output."""

    tree_line_start: int = 10
    tree_line_end: int = 20
    log_buffer_changes: bool = False
    log_changed_ranges: bool = False


class ConditionCode(Enum):
    """Condition codes informing clients of parse tree or buffer changes."""

    NEW_CLEAN_TREE = 1
    NEW_OUT_OF_DATE_TREE = 2
    PENDING_CHANGES = 3


class ActionTimer:
    """A class that times how long something takes.

    @start: Start time, in seconds, for this timer.
    """

    def __init__(self):
        self.start: float = time.time()

    def restart(self) -> None:
        """Restart this timer."""
        self.start = time.time()

    @property
    def elapsed(self) -> float:
        """The current elapsed time."""
        return time.time() - self.start


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

    def format_1(self) -> str:
        """Format contents using 1-based lines and columns."""
        bb = f'{self.start_byte} => {self.old_end_byte}->{self.new_end_byte}'
        a, _ = self.start_point
        c, _ = self.old_end_point
        e, _ = self.new_end_point
        frm = f'{a+1}'
        old_to = f'{c+1}'
        new_to = f'{e+1}'
        return f'Bytes: {bb} / Lines: {frm} => {old_to}->{new_to}'


@dataclass
class BackgroundFullParser:
    """A performer of a totally clean, background parse operation.

    I have seen evidence of the Tree-sittter tree and the Vim buffer
    occasionally becoming out of sync. My guess is that one of the following
    is occurring:

    - Vim is not generating correct buffer change notifications.
    - The vpe_sitter code is failing to react to all such notifications or
      is not correctly applying then to the Tree-sitter tree.
    - The tree-sitter tree is not correctly applying edits.

    This class arranges for a new tree to occasionally be created.

    Except, we do not really need this. Just an occasional new tree without
    edits.
    """


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
    pending_changes: list[SyntaxTreeEdit] = field(default_factory=list)
    tree: Tree | None = None
    timer: vpe.Timer | None = None
    changed_ranges: list = field(default_factory=list)

    parse_timeouts: int = 0
    parse_time: ActionTimer | None = None
    last_clean_time: ActionTimer = field(default_factory=ActionTimer)

    @property
    def active(self) -> bool:
        """Flag that is ``True`` when parsing is ongoing."""
        return self.parse_time is not None

    def start(self) -> None:
        """Start a new parsing operation."""
        if self.active:
            return

        if self.pending_changes:
            if self.tree is not None:
                for edit in self.pending_changes:
                    self.tree.edit(**edit._asdict())
            self.pending_changes[:] = []

        self.parser.timeout_micros = 5_000
        self.lines = list(self.listener.buf)
        self.code_bytes = '\n'.join(self.lines).encode('utf-8')
        self.parse_time = ActionTimer()
        self.parse_timeouts = 0
        self._try_parse()

    def add_edit(self, edit: SyntaxTreeEdit) -> None:
        """Add a pending tree edit to the backlog of edits.

        If no parse run is currently in progress, one is triggered. Otherwise
        a new run will be triggered when the current one finishes.
        """
        self.pending_changes.append(edit)
        if not self.active:
            self.parse_done_callback(ConditionCode.PENDING_CHANGES, [])
        vpe.call_soon_once(id(self), self.start)

    def _try_parse(self, _timer: vpe.Timer | None = None) -> None:
        try:
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
            if self.timer:
                self.timer = None
            self._handle_parse_completion(tree)

    def _handle_parse_completion(self, tree: Tree) -> None:

        parse_time = self.parse_time.elapsed
        self.parse_time = None

        def build_changed_ranges() -> list[range]:
            if self.tree:
                ranges = [
                    range(r.start_point.row, r.end_point.row + 1)
                    for r in self.tree.changed_ranges(tree)
                ]
                if debug_settings.log_changed_ranges:
                    s = [f'Tree-siter reports {len(ranges)} changes:']
                    for r in ranges:
                        s.append(f'    {r}')
                    print('\n'.join(s))
            else:
                ranges = []
            return ranges

        if not self.pending_changes:
            # Parsing has completed without any intervening buffer changes.
            #-print(
            #-    f'Parse completed cleanly in {parse_time:.4f}s')
            self.last_clean_time.restart()
            changed_ranges = build_changed_ranges()
            self.tree = tree
            self.dump()
            self.parse_done_callback(
                ConditionCode.NEW_CLEAN_TREE, changed_ranges)

        else:
            # The new tree is not clean. If not too much time has elapsed,
            # parse again to catch up.
            if self.last_clean_time.elapsed + parse_time < MAX_UNCLEAN_TIME:
                #-print(
                #-    f'Parse completed uncleanly in {parse_time:.4f}s,'
                #-    ' trying to catch up.'
                #-)
                vpe.call_soon_once(id(self), self.start)
            else:
                # Inform clients that the tree has changed but is not up to
                # date.
                #-print(
                #-    f'Parse completed uncleanly in {parse_time:.4f}s,'
                #-    ' too slow to try catching up.'
                #-)
                changed_ranges = build_changed_ranges()
                self.tree = tree
                self.dump()
                self.parse_done_callback(
                    ConditionCode.NEW_OUT_OF_DATE_TREE, changed_ranges)

                # ... and parse the changed code.
                vpe.call_soon_once(id(self), self.start)

    def _schedule_reparse(self) -> None:
        ms_delay = 10
        self.timer = vpe.Timer(ms_delay, self._try_parse)

    def dump(self):
        """Dump a printout of the tree."""
        if self.tree is None:
            return

        start_lidx = debug_settings.tree_line_start - 1
        end_lidx = debug_settings.tree_line_end
        if start_lidx >= end_lidx:
            return

        # I am not sure what the grammar name represents, nor how it can be
        # used. So I ignore it.
        show_grammar_name = False

        def put_node(node, field_name=''):

            a = tuple(node.start_point)
            b = tuple(node.end_point)

            no_overlap = start_lidx >= b[0] or end_lidx <= a[0]
            if not no_overlap:
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
    @tree_change_callbacks:
        A list of functions to be invoked upon code tree state changes.
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
        self.tree_change_callbacks: list[ParseCompleteCallback] = []
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

    def handle_parse_complete(
            self, code: ConditionCode, affected_lines: AffectedLines) -> None:
        """Update information following a (re)parse of the buffer's code.

        :affected_lines:
            A list of ranges identifying which lines need updating.
        """
        for callback in self.tree_change_callbacks:
            callback(code, affected_lines)

    def handle_changes(
            self,
            _buf: vpe.Buffer,
            start_lidx: int,
            end_lidx: int,
            added:int,
            ops: list[diffs.Operation],
        ) -> None:
        """Process changes for the associated buffer.

        This is invoked by Vim to report changes to the buffer. The start
        and end line indices are converted into `SyntaxTreeEdit` operation.
        One is added to the `end_lidx` before the `SyntaxTreeEdit` is created.
        This adjustment appear to be necessary to keep the Tree-sitter tree
        properly synchronised.

        :_buf:       The affected buffer, ignored because the buffer is known.
        :start_lidx: Start of affected line range.
        :end_lidx:   End of affected line range.
        :added:      The number of lines added or, if negative, deleted.
        :ops:        A list of the operations applied within the line range.
        """
        # The start offset and old end byte offset depend on the previously
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
        new_end_lidx = min(end_lidx + added, len(self.buf))
        new_end_byte = self.byte_offsets[new_end_lidx]

        # The start, old and new end points are more simply generated.
        start_point = Point(start_lidx, 0)
        old_end_point = Point(end_lidx, 0)
        new_end_point = Point(new_end_lidx, 0)

        # Update the parsing controller's pending edits. This will typically
        # trigger an incremental Tree-sitter reparse.
        edit = SyntaxTreeEdit(
            start_byte, old_end_byte, new_end_byte,
            start_point, old_end_point, new_end_point,
        )
        if debug_settings.log_buffer_changes:
            log(f'Handlechange: {start_lidx+1} {end_lidx+1} {added}')
            log(f'              edit={edit.format_1()}')
        self.in_progress_parse_operation.add_edit(edit)

    def add_parse_complete_callback(
            self, callback: ParseCompleteCallback,
        ) -> None:
        """Add a callback for code parsing completion."""
        self.tree_change_callbacks.append(callback)
        active = self.in_progress_parse_operation.active
        tree = self.in_progress_parse_operation.tree
        if tree is not None and not active:
            callback(ConditionCode.NEW_OUT_OF_DATE_TREE, [])


#: The debug settings object.
debug_settings = DebugSettings()
