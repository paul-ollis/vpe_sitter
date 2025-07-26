"""Support for 'listening' for buffer changes and updating syntax information.

This provides the `Listen` class, which can be attached to a buffer. It listens
for buffer changes and parses the contents in response.
"""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from enum import Enum
from itertools import accumulate
from typing import Callable, Final, NamedTuple, TypeAlias
from weakref import proxy

from tree_sitter import Parser, Tree

import vpe
from vpe import EventHandler, vim
from vpe.vpe_lib import diffs

#: A list of line ranges that need updating for the latest (re)parsing.
AffectedLines: TypeAlias = list[range] | None

#: A callback function for when a (re)parsing completes.
ParseCompleteCallback: TypeAlias = Callable[
    ['ConditionCode', AffectedLines], None]

#: How long the parse tree may be 'unclean' before clients are notified.
MAX_UNCLEAN_TIME = 0.2

#: A print-equivalent function that works inside Vim callbacks.
log = functools.partial(vpe.call_soon, print)


@dataclass
class DebugSettings:
    """Setting controlling debug output."""

    tree_line_start: int = -1
    tree_line_end: int = -1
    log_buffer_changes: bool = False
    log_changed_ranges: bool = False
    log_performance: bool = False

    @property
    def dump_tree(self) -> bool:
        """Flag indicating that the (partial) tree should be logded."""
        return self.tree_line_end > 0 and (
            self.tree_line_end >= self.tree_line_start)


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


class VimEventHandler(EventHandler):
    """A global event handler for critical Vim events."""
    def __init__(self):
        self.auto_define_event_handlers('VPE_ListenEventGroup')

    @EventHandler.handle('BufReadPost')
    def handle_buffer_content_loaded(self) -> None:
        """React to a buffer's contents being reloaded.

        Any listener for the buffer needs to be informed so that it can start
        over with a clean parse tree.
        """
        buf = vim.current.buffer
        store = buf.retrieve_store('syntax-sitter')
        if store is not None:
            listener = store.listener
            if listener is not None:
                listener.handle_bufer_reload()


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
    pending_changed_ranges: list = field(default_factory=list)

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
            self.pending_changed_ranges[:] = []
            if self.tree is not None:
                for edit in self.pending_changes:
                    self.tree.edit(**edit._asdict())
                    self.pending_changed_ranges.append(
                        range(
                            edit.start_point.row_index,
                            edit.new_end_point.row_index)
                    )
                if debug_settings.log_changed_ranges:
                    print(f'PAUL: {self.pending_changed_ranges}')

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

    def start_clean(self) -> None:
        """Start a completely clean tree build.

        Any in-progress build is abandoned, pending changes are discarded and
        a new tree construction is started.
        """
        if self.timer:
            self.timer.stop()
            self.timer = None
        self.pending_changes[:] = []
        self.parse_time = None
        self.tree = None
        self.start()

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
                ranges = merge_ranges(ranges, self.pending_changed_ranges)
                self.pending_changed_ranges[:] = []
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
            if debug_settings.log_performance:
                print(
                    f'Tree-sitter parsed cleanly in {parse_time:.4f}s')
            self.last_clean_time.restart()
            changed_ranges = build_changed_ranges()
            self.tree = tree
            if debug_settings.dump_tree:
                self.dump()
            self.parse_done_callback(
                ConditionCode.NEW_CLEAN_TREE, changed_ranges)

        else:
            # The new tree is not clean. If not too much time has elapsed,
            # parse again to catch up.
            if self.last_clean_time.elapsed + parse_time < MAX_UNCLEAN_TIME:
                if debug_settings.log_performance:
                    print(
                        f'Tree-sitter parsed uncleanly in {parse_time:.4f}s,'
                        ' trying to catch up.'
                    )
                vpe.call_soon_once(id(self), self.start)
            else:
                # Inform clients that the tree has changed but is not up to
                # date.
                if debug_settings.log_performance:
                    print(
                        f'Tree-sitter parse uncleanly in {parse_time:.4f}s,'
                        ' too slow to try catching up.'
                    )
                changed_ranges = build_changed_ranges()
                self.tree = tree
                if debug_settings.dump_tree:
                    self.dump()
                self.parse_done_callback(
                    ConditionCode.NEW_OUT_OF_DATE_TREE, changed_ranges)

                # ... and parse the changed code.
                vpe.call_soon_once(id(self), self.start)

    def _schedule_reparse(self) -> None:
        ms_delay = 10
        self.timer = vpe.Timer(ms_delay, self._try_parse)

    def dump(
            self, tree_line_start: int | None = None,
            tree_line_end: int | None = None,
        ):
        """Dump a representaion of part of the tree."""
        if self.tree is None:
            return

        if tree_line_start is not None:
            start_lidx = tree_line_start - 1
            end_lidx = tree_line_end
        else:
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
            a_lidx = a[0]
            b_lidx = b[0] + 1

            no_overlap = start_lidx >= b_lidx or end_lidx <= a_lidx
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
        if s:
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
    vim_event_handler: Final = VimEventHandler()

    def __init__(self, buf: vpe.Buffer, parser: Parser):
        self.buf = buf
        self.reload_count = 0
        self.parser: Parser = parser
        self.tree_change_callbacks: list[ParseCompleteCallback] = []
        self.in_progress_parse_operation = InprogressParseOperation(
            proxy(self), self.parser, self.handle_parse_complete)

        # On my computer, this code is over 10 times faster than using Vim's
        # line2byte function.
        self.byte_offsets = list(accumulate([
            len(line.encode('utf-8')) + 1 for line in self.buf], initial=0))

        self.listen_handle = buf.add_listener(
            self.handle_changes, raw_changes=False)
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
            vim_changes: list[dict] | None = None,
        ) -> None:
        """Process changes for the associated buffer.

        This is invoked by Vim to report changes to the buffer. The start
        and end line indices are converted into `SyntaxTreeEdit` operations.

        :_buf:        The affected buffer, ignored because the buffer is known.
        :start_lidx:  Start of affected line range.
        :end_lidx:    End of affected line range.
        :added:       The number of lines added or, if negative, deleted.
        :ops:         A list of the operations applied within the line range.
        :vim_changes: The original Vim generated list of changes or None.
        """
        # pylint: disable=too-many-arguments
        # pylint: disable=too-many-locals,too-many-positional-arguments
        # Special handling is required if Vim reports added lines starting
        # past the end of the buffer. This happens when, for example, when
        # executing normal('o') while on the last line.
        if start_lidx == len(self.byte_offsets) - 1:
            start_lidx = max(0, start_lidx - 1)

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
            s = []
            s.append('Handlechange:')
            s.append(f'   Lines: {start_lidx+1} {end_lidx+1} {added}')
            s.append(f'   Edit:  {edit.format_1()}')
            if vim_changes is not None:
                for op in vim_changes:
                    s.append(f'    {op}')
            log('\n'.join(s))

        self.in_progress_parse_operation.add_edit(edit)

    def handle_bufer_reload(self) -> None:
        """React to this buffer's contents being reloaded."""
        self.in_progress_parse_operation.start_clean()

    def add_parse_complete_callback(
            self, callback: ParseCompleteCallback,
        ) -> None:
        """Add a callback for code parsing completion."""
        self.tree_change_callbacks.append(callback)
        active = self.in_progress_parse_operation.active
        tree = self.in_progress_parse_operation.tree
        if tree is not None and not active:
            callback(ConditionCode.NEW_OUT_OF_DATE_TREE, [])

    def print_tree(self, tree_line_start: int, tree_line_end: int):
        """Print part of the syntax tree for this buffer."""
        self.in_progress_parse_operation.dump(tree_line_start, tree_line_end)


def merge_ranges(ranges_a: list[range], ranges_b: list[range]) -> list[range]:
    """Merge two lists of ranges, combining any averlapping ranges."""
    ranges = sorted(ranges_a + ranges_b, key=lambda r: (r.start, r.stop))
    if len(ranges) < 2:
        return ranges

    combined = []
    a = ranges.pop(0)
    b = ranges.pop(0)
    while True:
        overlap = not (a.stop < b.start or b.stop < a.start)
        if overlap:
            nr = range(min(a.start, b.start), max(a.stop, b.stop))
            combined.append(nr)
            a = b = None
        else:
            combined.append(a)
            a = b
            b = None

        if a is None:
            if ranges:
                a = ranges.pop(0)
        if ranges:
            b = ranges.pop(0)
        if a is None:
            return combined
        if b is None:
            combined.append(a)
            return combined


#: The debug settings object.
debug_settings = DebugSettings()
