"""Support for 'listening' for buffer changes and updating syntax information.

This provides the `Listen` class, which can be attached to a buffer. It listens
for buffer changes and parses the contents in response.
"""
from __future__ import annotations

import contextlib
import functools
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from itertools import accumulate
from pathlib import Path
from typing import Callable, ClassVar, Final, NamedTuple, TypeAlias
from weakref import proxy

from tree_sitter import Parser, Tree

import vpe
from vpe import EventHandler, vim

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


class ConditionCode(Enum):
    """Condition codes informing clients of parse tree or buffer changes."""

    NEW_CLEAN_TREE = 1
    NEW_OUT_OF_DATE_TREE = 2
    PENDING_CHANGES = 3


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
        bb = f'{self.start_byte} => {self.old_end_byte}->{self.new_end_byte}'
        a, _ = self.start_point
        c, _ = self.old_end_point
        e, _ = self.new_end_point
        frm = f'{a}'
        old_to = f'{c}'
        new_to = f'{e}'
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
        store = buf.retrieve_store('tree-sitter')
        if store is not None:
            listener = store.listener
            if listener is not None:
                listener.handle_buffer_reload()


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

    # A hack for change tracking.
    tree_ranges: list = field(default_factory=list)

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

        if self.continuation_timer is None:
            self.continuation_timer = vpe.Timer(
                RESUME_DELAY, self._continue_parse, repeat=-1)
            self.continuation_timer.pause()

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
        self.lines = list(self.listener.buf)
        self.code_bytes = '\n'.join(self.lines).encode('utf-8')
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
            self.listener.track_tree(
                ConditionCode.PENDING_CHANGES, [], [])
        vpe.call_soon_once(id(self), self.start)

    def start_clean(self) -> None:
        """Start a completely clean tree build.

        Any in-progress build is abandoned, pending changes are discarded and
        a new tree construction is started.
        """
        if self.continuation_timer is not None:
            self.continuation_timer.pause()
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
            # The only known cause is a timeout.
            self.parse_time.pause()
            self._schedule_continuation()

        else:
            self.parse_time.pause()
            if self.continuation_timer:
                self.continuation_timer.pause()
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
                self.tree_ranges = tree_ranges
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
            self.listener.track_tree(
                ConditionCode.NEW_CLEAN_TREE, self.tree_ranges, changed_ranges)

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
                self.listener.track_tree(
                    ConditionCode.NEW_OUT_OF_DATE_TREE, self.tree_ranges,
                    changed_ranges)

                # ... and parse the changed code.
                vpe.call_soon_once(id(self), self.start)

    def _schedule_continuation(self) -> None:
        """Schedule a continuation of the current parse operation."""
        if self.continuation_timer is None:
            self.continuation_timer = vpe.Timer(
                RESUME_DELAY, self._continue_parse, repeat=-1)
        self.continuation_timer.resume()

    def _continue_parse(self, _timer):
        """Continue parsing if suspended due to a timeout."""
        if self.continuation_timer:
            self.continuation_timer.pause()
        if self.paused:
            self._try_parse()

    def dump(self, tree_line_start: int = -1, tree_line_end: int = -1):
        """Dump a representaion of part of the tree."""
        if self.tree is None:
            return

        if tree_line_start >= 1:
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
    tracker: ClassVar[Tracker | None] = None

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
            self.handle_changes, raw_changes=True, ops=False)
        self.paused = False
        self.in_progress_parse_operation.start()

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
            raw_changes: list[dict] | tuple = (),
        ) -> None:
        """Process changes for the associated buffer.

        This is invoked by Vim to report changes to the buffer. The start
        and end line indices are converted into `SyntaxTreeEdit` operations.

        Each detailed raw change provides lnum, end, col and added. The Vim
        docs are not very clear to me so here are my observations:
        The lnum and end define an exclusive 1-based range, for example
        lnum=4, end=6 means lines 4 and 5 but not 6. The added value is
        posistive when lines are added a negative when lines are removed. In
        the following description I use the form a->b[+-]added. Examples:
        4->6+2 means lnum=4, end=6 and added=2.

        Here are a bunch of examples::

            Delete line 3:                   3->4-1
            Sel del lines 3->6:              3->7-4
            Add line after 3:                4->4+1
            Split line 3:                    3->4+1
            Put line after 3:                4->4+1
            Put line before 3:               3->3+1
            Do '3dd' on line 3:              3->6-3
            Sel within line 'v' 3->4, del:   3->4+0    col=5
                                             4->5+0    col=1
                                             3->4+0    col=5
                                             4->5-1    col=1
            Undo previous:                   2->5+1
            Insert in line 3:                3->4+0

        :_buf:        The affected buffer, ignored because the buffer is known.
        :start_lidx:  Start of affected line range.
        :end_lidx:    End of affected line range.
        :added:       The number of lines added or, if negative, deleted.
        """
        # pylint: disable=too-many-arguments
        # pylint: disable=too-many-locals,too-many-positional-arguments
        if self.tracker:
            args = start_lidx, end_lidx, added
            raw_changes = [dict(ch) for ch in raw_changes]

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
        if self.paused:
            return

        # The new end byte offset uses the newly calculated line byte offsets.
        new_end_lidx = min(end_lidx + added, len(self.buf))
        new_end_byte = self.byte_offsets[new_end_lidx]

        # The start, old and new end points are more simply generated.
        start_point = Point(start_lidx, 0)
        old_end_point = Point(end_lidx, 0)
        new_end_point = Point(new_end_lidx, 0)

        # Update the parsing controller's pending edits. This will typically
        # trigger an immediate incremental Tree-sitter reparse, but reparsing
        # may be delayed by an already in progress parse operation.
        edit = SyntaxTreeEdit(
            start_byte, old_end_byte, new_end_byte,
            start_point, old_end_point, new_end_point,
        )
        if debug_settings.log_buffer_changes:
            s = []
            s.append('Handle change:')
            s.append(f'   Lines: {start_lidx+1} {end_lidx+1} {added}')
            s.append(f'   Edit:  {edit.format_1()}')
            log('\n'.join(s))

        self.in_progress_parse_operation.add_edit(edit)

        if self.tracker:
            self.tracker.add_record(self.buf, args, edit, raw_changes)

    def handle_buffer_reload(self) -> None:
        """React to this buffer's contents being reloaded."""
        if debug_settings.active:
            log('Start clean parse due to buffer load')
        self.in_progress_parse_operation.start_clean()

    def pause(self, flag: bool) -> None:
        """Pause or resume parsing."""
        if self.paused and not flag:
            self.paused = False
            self.in_progress_parse_operation.start_clean()
        elif flag and not self.paused:
            self.paused = True

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
    @classmethod
    def track(cls, flag: bool) -> None:
        """Start or stop detailed change tracking."""
        if flag:
            if not cls.tracker:
                cls.tracker = Tracker()
        else:
            cls.tracker = None

    def track_tree(
            self,
            code: ConditionCode,
            tree_lines: AffectedLines,
            all_lines: AffectedLines
        ) -> None:
        """Add a tree tracking record."""
        if self.tracker:
            self.tracker.track_tree(self.buf, code, tree_lines, all_lines)


class Tracker:
    """Class to manage the detail change tracking log."""

    def __init__(self):
        self.track_dir = Path('~/tmp/ts_log').expanduser()
        if self.track_dir.exists():
            shutil.rmtree(self.track_dir)
        self.track_dir.mkdir(exist_ok=True)

        ignore_path = self.track_dir / '.gitignore'
        ignore_path.write_text('log.txt')

        self.log_path = self.track_dir / 'log.txt'
        self.log_file = self.log_path.open(
            mode='wt', encoding='utf-8', buffering=1)
        self.log_file.write('log.txt\n')
        self.file_map: dict[str, str] = {}

        self.exec_git(['git', 'init'])
        self.exec_git(['git', 'add', str(ignore_path)])
        self.exec_git(['git', 'commit', '-am', 'Started'])

    def add_record(self, buf, args, edit, raw_changes):
        """Add a tracker record."""
        buf_path = Path(buf.name)
        if buf.name not in self.file_map:
            pathname = f'F{len(self.file_map)}_{buf_path.name}'
            self.file_map[buf.name] = pathname
        pathname = self.file_map[buf.name]
        with contextlib.chdir(self.track_dir):
            with open(pathname, mode='wt', encoding='utf-8') as f:
                f.write('\n'.join(buf))
                f.write('\n')

        self.exec_git(['git', 'add', pathname])
        self.exec_git(['git', 'commit', '-m', f'Record {buf.name}'])
        text = self.exec_git(['git', 'log', '-1', '--oneline'])
        commit = text.split(None, 1)[0]

        self.log_file.writelines([
            f'Commit: {commit}\n',
            f'Args: {args}\n',
            f'Edit: {edit}\n',
            f'Raw: {raw_changes}\n',
        ])

    def track_tree(
            self,
            buf,
            code: ConditionCode,
            tree_lines: AffectedLines,
            all_lines: AffectedLines
        ) -> None:
        """Add a tree tracking record."""
        buf_path = Path(buf.name)
        if buf.name not in self.file_map:
            pathname = f'F{len(self.file_map)}_{buf_path.name}'
            self.file_map[buf.name] = pathname
        pathname = self.file_map[buf.name]
        self.log_file.writelines([
            f'File: {pathname}\n',
            f'Code: {code}\n',
            f'Tree_lines: {tree_lines}\n',
            f'All_lines: {all_lines}\n',
        ])

    def exec_git(self, args: list[str]) -> str:
        """Execute a git command, logging any errors."""
        execute = functools.partial(
            subprocess.run, capture_output=True, encoding='utf-8', errors='ignore')
        with contextlib.chdir(self.track_dir):
            res = execute(args)
        if res.stderr:
            log(res.stderr)
        return res.stdout


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
