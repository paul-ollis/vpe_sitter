"""Support for 'listening' for buffer changes and updating syntax information.

This provides the `Listen` class, which can be attached to a buffer. It listens
for buffer changes and parses the contents in response.
"""
from __future__ import annotations

import functools
import time
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from itertools import accumulate
from typing import Callable, Final, NamedTuple, TypeAlias
from weakref import proxy

from tree_sitter import Parser, Tree

import vpe
from vpe import EventHandler, vim

# This is temporary. It allows experimentation with the listen_add buffering
# work-around.
WORKAROUND_TESTING = Path('~/WORKAROUND_TESTING').expanduser().exists()

#: A list of line ranges that need updating for the latest (re)parsing.
AffectedLines: TypeAlias = list[range] | None

#: A callback function for when a (re)parsing completes.
ParseCompleteCallback: TypeAlias = Callable[
    ['ConditionCode', AffectedLines], None]

#: How long the parse tree may be 'unclean' before clients are notified.
MAX_UNCLEAN_TIME = 0.2

#: The timeout (in microseconds) for the Tree-sitter parser.
PARSE_TIMEOUT = 20_000

#: The delay (in milliseconds) before continuing a timed out Tree-sitter parse
#: operation.
RESUME_DELAY = 1

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

    @property
    def active(self) -> bool:
        """Flag indicating that some debugging is active."""
        if self.dump_tree:
            return True
        flag = self.log_changed_ranges or self.log_buffer_changes
        flag = flag or self.log_performance
        return flag

    def set_all(self, flag: bool) -> None:
        """Set all debug flags on or off."""
        self.log_buffer_changes = flag
        self.log_changed_ranges = flag
        self.log_performance = flag


class ConditionCode(Enum):
    """Condition codes informing clients of parse tree or buffer changes."""

    NEW_CLEAN_TREE = 1
    NEW_OUT_OF_DATE_TREE = 2
    PENDING_CHANGES = 3
    RELOAD = 4


class ActionTimer:
    """A class that times how long something takes.

    @start:
        Start time, in seconds, for this timer.
    @partials:
        A list of (start, stop) times which capture the active periods
        between pauses.
    """

    def __init__(self):
        self.start: float = time.time()
        self.partials: list[tuple[float, float | None]] = [(self.start, None)]
        self.active = False

    def pause(self) -> None:
        """Add a pause point."""
        a, _ = self.partials[-1]
        b = time.time()
        self.partials[-1] = a, b

    def resume(self) -> None:
        """Continue after a pause."""
        if self.partials[-1][1] is not None:
            self.partials.append((time.time(), None))

    def restart(self) -> None:
        """Restart this timer."""
        self.start = time.time()
        self.partials = [(self.start, None)]
        self.active = True

    def stop(self) -> None:
        """Stop this timer."""
        self.active = False

    @property
    def paused(self) -> bool:
        """Test if this timer is currently paused."""
        return self.active and self.partials[-1][1] is not None

    @property
    def elapsed(self) -> float:
        """The current elapsed time."""
        return time.time() - self.start

    @property
    def used(self) -> float:
        """The time used within the elapses time."""
        times = [b - a for a, b in self.partials if b is not None]
        return sum(times)


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
        bb = f'{self.start_byte}=>{self.old_end_byte}->{self.new_end_byte}'
        a, _ = self.start_point
        c, _ = self.old_end_point
        e, _ = self.new_end_point
        frm = f'{a}'
        old_to = f'{c}'
        new_to = f'{e}'
        return f'Bytes: {bb} / Lines: {frm}=>{old_to}->{new_to}'


class VimEventHandler(EventHandler):
    """A global event handler for critical Vim events."""
    def __init__(self):
        self.auto_define_event_handlers('VPE_ListenEventGroup')
        self.callbacks: dict[str, list[Callable[[], None]]] = {}

    def add_callback(self, event: str, func: Callable[[], None]) -> None:
        """Add a function to be invoked for an event."""
        if event not in self.callbacks:
            self.callbacks[event] = []
        self.callbacks[event].append(func)

    def _invoke_callbacks_for_event(self, event: str) -> None:
        for func in self.callbacks.get(event, ()):
            func()

    @EventHandler.handle('BufReadPost')
    def handle_buffer_content_loaded(self) -> None:
        """React to a buffer's contents being reloaded.

        Any listener for the buffer needs to be informed so that it can start
        over with a clean parse tree.
        """
        buf = vim.current.buffer
        store = buf.retrieve_store('tree-sitter')
        if store is not None:
            listener = store.listener
            if listener is not None:
                listener.handle_buffer_reload()

    @EventHandler.handle('SafeState')
    def handle_safe_state(self) -> None:
        """React to the safe state being entered."""
        self._invoke_callbacks_for_event('SafeState')

    @EventHandler.handle('SafeStateAgain')
    def handle_safe_state_again(self) -> None:
        """React to the safe again state being entered."""
        self._invoke_callbacks_for_event('SafeAgainState')


@dataclass
class InProgressParseOperation:
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
    @continuation_timer:
        A `vpe.Timer` used to continue a long parse operation.
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
    continuation_timer: vpe.Timer | None = None
    changed_ranges: list = field(default_factory=list)
    pending_changed_ranges: list = field(default_factory=list)
    parse_time: ActionTimer = ActionTimer()
    last_clean_time: ActionTimer = field(default_factory=ActionTimer)

    @property
    def active(self) -> bool:
        """Flag that is ``True`` when parsing is ongoing."""
        return self.parse_time.active

    @property
    def paused(self) -> bool:
        """Flag that is ``True`` when parsing has paused."""
        return self.parse_time.paused

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
            self.pending_changes[:] = []

        self.parser.timeout_micros = PARSE_TIMEOUT
        self.code_bytes = '\n'.join(self.listener.buf).encode('utf-8')
        self.parse_time.restart()
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
        self.pending_changes[:] = []
        self.tree = None
        self.start()

    def _try_parse(self, _timer: vpe.Timer | None = None) -> None:
        """Try to parse the buffer's contents, continuing after timeouts.

        This method will re-schedule itself in the event that the Tree-sitter
        parser times out, effectivey executing parsing as a background
        (time-sliced) operation.
        """
        self.parse_time.resume()
        try:
            if self.tree is not None:
                tree = self.parser.parse(
                    self.code_bytes, old_tree=self.tree, encoding='utf-8')
            else:
                tree = self.parser.parse(self.code_bytes, encoding='utf-8')

        except ValueError:
            # The only known cause is a timeout. The exception object does not
            # provide useful diagnostics, so we simple have to assume.
            self.parse_time.pause()
            self._schedule_continuation()

        else:
            self.parse_time.pause()
            self._handle_parse_completion(tree)

    def _handle_parse_completion(self, tree: Tree) -> None:
        elapsed = self.parse_time.elapsed
        used = self.parse_time.used
        if debug_settings.log_performance:
            time_str = f'{elapsed=:.4f}s, {used=:.4f}s'
            time_str += f' continuations={len(self.parse_time.partials) - 1}'
        self.parse_time.stop()

        def build_changed_ranges() -> list[range]:
            if self.tree:
                tree_ranges = [
                    range(r.start_point.row, r.end_point.row + 1)
                    for r in self.tree.changed_ranges(tree)
                ]
                vim_ranges = self.pending_changed_ranges
                ranges = merge_ranges(tree_ranges, vim_ranges)
                if debug_settings.log_changed_ranges:
                    s = [f'Tree-siter reports {len(tree_ranges)} changes:']
                    for r in tree_ranges:
                        s.append(f'    {r}')
                    s.append(f'Vim reported {len(vim_ranges)} changes:')
                    for r in vim_ranges:
                        s.append(f'    {r}')
                    s.append(f'Merged {len(ranges)} changes:')
                    for r in ranges:
                        s.append(f'    {r}')
                    log('\n'.join(s))
                self.pending_changed_ranges[:] = []
            else:
                ranges = []
            return ranges

        if not self.pending_changes:
            # Parsing has completed without any intervening buffer changes.
            if debug_settings.log_performance:
                log(
                    f'Tree-sitter parsed cleanly in {time_str}')
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
            if self.last_clean_time.elapsed + elapsed < MAX_UNCLEAN_TIME:
                if debug_settings.log_performance:
                    log(
                        f'Tree-sitter parsed uncleanly in {time_str},'
                        ' trying to catch up.'
                    )
                vpe.call_soon_once(id(self), self.start)
            else:
                # Inform clients that the tree has changed but is not up to
                # date.
                if debug_settings.log_performance:
                    log(
                        f'Tree-sitter parsed uncleanly in {time_str},'
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

    def _schedule_continuation(self) -> None:
        """Schedule a continuation of the current parse operation."""
        self.continuation_timer = vpe.Timer(RESUME_DELAY, self._continue_parse)

    def _continue_parse(self, _timer):
        """Continue parsing if suspended due to a timeout."""
        self._try_parse()

    def dump(
            self, tree_line_start: int = -1, tree_line_end: int = -1,
            show_ranges: bool = False):
        """Dump a representaion of part of the tree."""
        if self.tree is None:
            return

        if tree_line_start < -1:
            # Whole tree wanted.
            start_lidx = 0
            end_lidx = len(self.listener.buf)
        elif tree_line_start >= 1:
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
                if show_ranges:
                    s.append(f'{pad[-1]}{name} {a}->{b}')
                else:
                    s.append(f'{pad[-1]}{name}')

                pad.append(pad[-1] + '    ')
                for i, child in enumerate(node.children):
                    field_name = node.field_name_for_child(i)
                    put_node(child, field_name)
                pad.pop()

        s: list[str] = []
        pad = ['']
        put_node(self.tree.root_node)
        if s:
            log('\n'.join(s))


class Listener:
    """Per-buffer handler that uses buffer changes to run Tree-sitter.

    @buf:
        The buffer being monitored for changes.
    @parser:
        The Tree-sitter `Parser` user to (re)parse.
    @tree_change_callbacks:
        A list of functions to be invoked upon code tree state changes.
    @in_progress_parse_operation:
        A `InProgressParseOperation` object that runs parse operations as
        a "background" operation.
    @byte_offsets:
        The byte offsets for the start of each line in the buffer.
    @listen_handle:
        The Vim provided handle for the registered buffer listener.
    """
    # pylint: disable=too-many-instance-attributes
    listen_handle: vpe.BufListener
    in_progress_parse_operation: InProgressParseOperation
    vim_event_handler: Final = VimEventHandler()
    change_info: list[int]
    track_buf: list[str]
    ch_indices: list[None | int]

    def __init__(self, buf: vpe.Buffer, parser: Parser):
        self.buf = buf
        self.reload_count = 0
        self.parser: Parser = parser
        self.tree_change_callbacks: list[ParseCompleteCallback] = []
        self._reset_tracking()
        self.in_progress_parse_operation = InProgressParseOperation(
            proxy(self), self.parser, self.handle_parse_complete)

        # On my computer, this code is over 10 times faster than using Vim's
        # line2byte function.
        self.byte_offsets = list(accumulate([
            len(line.encode('utf-8')) + 1
            for line in self.track_buf], initial=0))

        unbuffered = not WORKAROUND_TESTING
        self.listen_handle = buf.add_listener(
            self.handle_changes, ops=False, unbuffered=unbuffered)
        self.ignore_report: bool = False
        self.simulate_failure: bool = False
        self.buffered_changes: list = []
        self.in_progress_parse_operation.start()
        self.vim_event_handler.add_callback(
            'SafeAgainState', self._apply_changes)

    @property
    def tree(self) -> Tree | None:
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

    def _handle_raw_change(self, raw_change: dict) -> None:
        """Handle a single raw vim change notification."""

    def handle_changes(
            self,
            _buf: vpe.Buffer,
            start_lidx: int,
            end_lidx: int,
            added:int,
        ) -> None:
        """Process changes for the associated buffer.

        This is invoked by Vim to report changes to the buffer.

        :_buf:        The affected buffer, ignored because the buffer is known.
        :start_lidx:  Start of affected line range.
        :end_lidx:    End of affected line range.
        :added:       The number of lines added or, if negative, deleted.
        """
        if self.ignore_report:
            return  # Only set when recovering from a buffer sync error.

        if debug_settings.log_buffer_changes:
            s = []
            a = start_lidx + 1
            b = end_lidx + 1
            s.append(f'Vim reports change for buffer {self.buf.number}:')
            s.append(f'   Lines (1-based):   {a}=>{b} {added}')
            s.append(f'   Track buf old len: {len(self.track_buf)}')
            log('\n'.join(s))

        # Apply the changes to the shadow buffer.
        a, b, n = start_lidx, end_lidx, added
        if self.change_info[0] < 0:
            self.change_info[:2] = [a, b]
            self.ch_indices = list(range(len(self.track_buf) + 1))

        if n == 0:
            start = self.ch_indices[a]
            end = self.ch_indices[b]
            self.track_buf[a:b] = self.buf[a:b]
        elif n > 0:
            start = self.ch_indices[a]
            end = self.ch_indices[b]
            self.track_buf[a:b] = self.buf[a:b + n]
            self.ch_indices[b:b] = [None] * n
        else:
            start = self.ch_indices[a]
            end = self.ch_indices[b]
            self.track_buf[a:b] = self.buf[a:b + n]
            del self.ch_indices[a - n:b]
        if start is not None:
            self.change_info[0] = min(self.change_info[0], start)
        if end is not None:
            self.change_info[1] = max(self.change_info[1], end)

        if debug_settings.log_buffer_changes:
            s = []
            s.append(f'   Track buf new len: {len(self.track_buf)}')
            log('\n'.join(s))

    def _do_apply_changes(
            self, start_lidx: int, end_lidx: int, added: int) -> None:
        """Tell the `InProgressParseOperation` about recent tracked changes."""
        # pylint: disable=too-many-locals

        # Special handling is required if Vim reports added lines starting
        # past the end of the buffer. This happens when, for example, when
        # executing normal('o') while on the last line.
        if start_lidx >= len(self.byte_offsets) - 1:
            start_lidx = max(0, len(self.byte_offsets) - 2)

        # TODO: Why is the next line required?
        end_lidx = min(end_lidx, len(self.byte_offsets) - 1)

        # The start offset and old end byte offset depend on the previously
        # calculated line byte offsets.
        start_byte = self.byte_offsets[start_lidx]
        old_end_byte = self.byte_offsets[end_lidx]

        # The line byte offsets need to be updated based on the new buffer
        # contents.
        start_offset = self.byte_offsets[start_lidx]
        self.byte_offsets[start_lidx:] = list(accumulate(
            [len(line.encode('utf-8')) + 1
             for line in self.track_buf[start_lidx:]],
            initial=start_offset)
        )

        # TODO: This is bug detection code.
        byte_offsets = list(accumulate([
            len(line.encode('utf-8')) + 1
            for line in self.buf], initial=0))
        failed = False
        if len(byte_offsets) != len(self.byte_offsets):
            log(
                f'OFFSETS FAIL: {len(byte_offsets)=}'
                f' {len(self.byte_offsets)=}')
            failed = True
        else:
            for i, (a, b) in enumerate(zip(byte_offsets, self.byte_offsets)):
                if a != b:
                    log(
                        f'OFFSET FAIL: line={i}'
                        f'\n    buf    ={a!r}'
                        f'\n    tracked={b!r}')
                    failed = True
                    break
        if failed:
            self.byte_offsets = byte_offsets

        # The new end byte offset uses the newly calculated line byte
        # offsets.
        new_end_lidx = min(end_lidx + added, len(self.buf))
        new_end_byte = self.byte_offsets[new_end_lidx]

        # The start, old and new end points are more simply generated.
        start_point = Point(start_lidx, 0)
        old_end_point = Point(end_lidx, 0)
        new_end_point = Point(new_end_lidx, 0)

        # Update the parsing controller's pending edits. This will
        # typically trigger an immediate incremental Tree-sitter reparse,
        # but reparsing may be delayed by an already in progress parse
        # operation.
        edit = SyntaxTreeEdit(
            start_byte, old_end_byte, new_end_byte,
            start_point, old_end_point, new_end_point,
        )
        if debug_settings.log_buffer_changes:
            s = []
            a = start_lidx + 1
            b = end_lidx + 1
            s.append('Handle change:')
            s.append(f'   Line (1-based): {a}=>{b} {added}')
            s.append(f'   Edit:           {edit.format_1()}')
            log('\n'.join(s))

        self.in_progress_parse_operation.add_edit(edit)

    def _apply_changes(self):
        """Process accumulated tracked changes."""
        start_lidx, end_lidx, old_len = self.change_info
        if start_lidx < 0:
            return

        added = len(self.track_buf) - old_len
        failed = False
        if self.simulate_failure:
            self.track_buf.append('')
            self.simulate_failure= False
        if len(self.buf) != len(self.track_buf):
            log(f'TRACK FAIL: {len(self.buf)=} {len(self.track_buf)=}')
            failed = True
        else:
            for i, (a, b) in enumerate(zip(self.buf, self.track_buf)):
                if a != b:
                    log(
                        f'TRACK FAIL: line={i}'
                        f'\n    buf    ={a!r}'
                        f'\n    tracked={b!r}')
                    failed = True
                    break

        if failed:
            # The assumption here is that this is due to report buffering
            # issues in an older version of Vim. Careful steps are required to
            # try to avoid the (single) buffered report from interfering with
            # our recovery efforts.
            self.ignore_report = True
            vim.listener_flush(self.buf.number)
            self.listen_handle.stop_listening()
            self.ignore_report = False
            unbuffered = not WORKAROUND_TESTING
            self.listen_handle = self.buf.add_listener(
                self.handle_changes, ops=False, unbuffered=unbuffered)

            self._reset_tracking()
            self.in_progress_parse_operation.start_clean()
        else:
            self._do_apply_changes(start_lidx, end_lidx, added)
            self.change_info = [-1, -1, len(self.track_buf)]

    def handle_buffer_reload(self) -> None:
        """React to this buffer's contents being reloaded."""
        if debug_settings.active:
            log('Start clean parse due to buffer load')
        self._reset_tracking()
        self.in_progress_parse_operation.start_clean()
        self.in_progress_parse_operation.parse_done_callback(
            ConditionCode.RELOAD, [])

    def add_parse_complete_callback(
            self, callback: ParseCompleteCallback,
        ) -> None:
        """Add a callback for code parsing completion."""
        self.tree_change_callbacks.append(callback)
        active = self.in_progress_parse_operation.active
        tree = self.in_progress_parse_operation.tree
        if tree is not None and not active:
            callback(ConditionCode.NEW_OUT_OF_DATE_TREE, [])

    def print_tree(
            self, tree_line_start: int, tree_line_end: int,
            show_ranges: bool = False):
        """Print part of the syntax tree for this buffer."""
        self.in_progress_parse_operation.dump(
            tree_line_start, tree_line_end, show_ranges=show_ranges)

    def _reset_tracking(self):
        self.track_buf = list(self.buf)
        self.byte_offsets = list(accumulate([
            len(line.encode('utf-8')) + 1
            for line in self.track_buf], initial=0))
        self.change_info = [-1, -1, len(self.track_buf)]
        self.ch_indices = []


def merge_ranges(ranges_a: list[range], ranges_b: list[range]) -> list[range]:
    """Merge two lists of ranges, combining any averlapping ranges."""
    ranges = sorted(ranges_a + ranges_b, key=lambda r: (r.start, r.stop))
    if len(ranges) < 2:
        return ranges

    empty = range(-1, -1)
    combined = []
    a = ranges.pop(0)
    b = ranges.pop(0)
    while True:
        overlap = not (a.stop < b.start or b.stop < a.start)
        if overlap:
            nr = range(min(a.start, b.start), max(a.stop, b.stop))
            combined.append(nr)
            a = b = empty
        else:
            combined.append(a)
            a = b
            b = empty

        if a is empty:
            if ranges:
                a = ranges.pop(0)
        if ranges:
            b = ranges.pop(0)
        if a is empty:
            return combined
        if b is empty:
            combined.append(a)
            return combined


#: The debug settings object.
debug_settings = DebugSettings()
