"""Support for 'listening' for buffer changes and updating syntax information.

This is the back bone of the Aware framework.
"""
from __future__ import annotations

import functools
import time
from array import array
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import accumulate
from typing import Callable, MutableSequence, NamedTuple, Protocol, TypeAlias
from weakref import proxy

from tree_sitter import Parser, Query, Tree

import vpe
from vpe.vpe_lib import diffs

#: This line offset index is used to indicate the end of line.
TO_END_OF_LINE = 0x7fff_ffff

#: A within-line syntax item.
#:
#: This identifies a range of characters (codepoints) on a line that represents
#: a syntatical item or part of one that extends to the next and/or previous
#: line.
#:
#: The integers define a (Python) character range and the string is the name of
#: the syntax item assigned by Tree-sitter.
InlineSyntaxItem: TypeAlias = tuple[int, int, str]

log = functools.partial(vpe.call_soon, print)

#: The maximum offset, indicating full range, used by Tree-sitter.
MAX_INT = 4294967295

#: A list of line ranges that need updating for the latest (re)parsing.
AffectedLines: TypeAlias = list[tuple[int, int]]

#: A callback function for when a (re)parsing completes.
ParseCompleteCallback: TypeAlias = Callable[[AffectedLines], None]


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


#                a    b
#   -------------|----|-------
#             |---.|
#             |---|
#   -------------|----|-------

#                a    b
#   -------------|----|-------
#             |----|
#             |---.|
#   -------------|-----|-------

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
    @affected_lines:
        A list of line ranges that need updating for the latest (re)parsing.
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
    affected_lines: AffectedLines = field(default_factory=list)
    tree: Tree | None = None
    timer: vpe.Timer | None = None

    def start(self) -> None:
        """Start a new parsing operation."""

        def update_changed(start_point, old_end_point, new_end_point):
            start_lidx = start_point.row_index
            new_end_lidx = new_end_point.row_index
            old_end_lidx = old_end_point.row_index
            delta = old_end_lidx - new_end_lidx

            # Adjust existing ranges.
            if delta != 0:
                for i, (a, b) in enumerate(self.affected_lines):
                    if b <= start_lidx:
                        # Edit after this change.
                        continue

                    if old_end_lidx <= a:
                        # Edit before this change.
                        a += delta
                        b += delta

                    else:
                        # Edit overlaps this change.
                        if delta < 0:
                            a += delta
                        else:
                            b += delta
                    self.affected_lines[i] = max(0, a), max(b, 0)

            # Add the new range
            self.affected_lines.append((start_lidx, new_end_lidx))

        self.affected_lines[:] = []
        if self.pending_changes:
            if self.tree is not None:
                for edit in self.pending_changes:
                    self.tree.edit(**edit._asdict())
                    update_changed(
                        edit.start_point,
                        edit.old_end_point,
                        edit.new_end_point,
                    )
            self.pending_changes[:] = []

        self.active = True
        self.lines = list(self.listener.buf)
        self.code_bytes = '\n'.join(self.lines).encode('utf-8')
        self.parser.timeout_micros = 5_000
        self._try_parse()

    def add_edit(self, edit: SyntaxTreeEdit) -> None:
        """Add a pending tree edit to the backlog of edits.

        If no parse run is currently in progress, one is triggered. Otherwise
        a new run will be triggered when the current one finishes.
        """
        print("Add edit", edit)
        self.pending_changes.append(edit)
        if not self.active:
            vpe.call_soon(self.start)

    def _try_parse(self, _timer: vpe.Timer | None = None) -> None:
        try:
            tree = self.parser.parse(self.code_bytes, encoding='utf-8')
        except ValueError:
            # The only known cause is a timeout.
            self._schedule_reparse()
            # print('Parsing continues')
        else:
            if self.tree:
                changed_ranges = tree.changed_ranges(self.tree)
            else:
                changed_ranges = []
            for rng in changed_ranges:
                self.affected_lines.append(
                    (rng.start_point.row, rng.end_point.row))
            self.tree = tree
            self.active = False
            if self.timer:
                self.timer = None
            print(f'New tree: {tree.root_node=}')
            print(f'          {tree.included_ranges=}')
            print(f'          {self.affected_lines=}')
            self.parse_done_callback(self.affected_lines)

            if self.pending_changes:
                vpe.call_soon(self.start)

    def _schedule_reparse(self) -> None:
        ms_delay = 10
        self.timer = vpe.Timer(ms_delay, self._try_parse)


class Listener:
    """Per-buffer handler that uses buffer changes to run Tree-sitter.

    @buf:
        The buffer being monitored for changes.
    @parser:
        The Tree-sitter `Parser` user to (re)parse.
    @query:
        The tree-sitter `Query` used to extract syntax elements from the tree.
        TODO: Not used - I think.
    @syntax_line_spans:
        A dictionary like object that maps line indices to syntax information.
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

    def __init__(self, buf: vpe.Buffer, parser: Parser, query: Query):
        self.buf = buf
        self.parser: Parser = parser
        self.query: Query = query
        self.syntax_line_spans = SyntaxLineSpans()
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
        self.syntax_line_spans.set_snapshot(
            lines=self.in_progress_parse_operation.lines,
            query=self.query,
            tree=self.in_progress_parse_operation.tree,
        )
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
        log(f'Change: {start_lidx=} {end_lidx=} {added=}')
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
        log(f'    {start_byte=} {old_end_byte=} {new_end_byte=}')
        log(f'    {start_point=} {old_end_point=} {new_end_point=}')

    def add_parse_complete_callback(
            self, callback: ParseCompleteCallback,
        ) -> None:
        """Add a callback for code parsing completion."""
        self.parse_complete_callbacks.append(callback)
        active = self.in_progress_parse_operation.active
        tree = self.in_progress_parse_operation.tree
        if tree is not None and not active:
            callback([])


class SyntaxLineSpans:
    """Lazy evaluated pseudo dictionary mapping lines to syntax information.

    This represents a snapshot for a given buffer. The line and column indices
    provided may, for **very** short periods of time, not perfectly map onto
    the buffer's current content. So suitable care must be taken by user's of
    this mapping.

    Args:
        text_area_widget: The associated `TextArea` widget.
    """

    BLOCK_SIZE = 50

    def __init__(self):
        #: The lines from which the syntax tree was generated.
        self._lines: list[str] = []

        #: The tree-sitter tree from which to genrate highlights.
        self._tree: Tree | None = None

        #: The tree-sitter query used to generate highlights from the tree.
        self._query: Query | None = None

        #: The set of already highlighted blocks, BLOCK_SIZE lines per block.
        self._highlighted_blocks: set[int] = set()

        #: A cache mapping line index to a list of InlineSyntaxItem instances.
        self._highlights: dict[int, list[InlineSyntaxItem]] = defaultdict(list)

        self.times: list[float] = []

    def debug_reset(self) -> None:
        """Yada."""
        self.times[:] = []

    @property
    def tot_time(self) -> float:
        """The total time spent building the map."""
        return sum(self.times)


    @property
    def line_count(self) -> int:
        """The number of lines in the map."""
        return len(self._lines)

    def copy(self) -> SyntaxLineSpans:
        """Create a copy of this highlight map."""
        # pylint: disable=protected-access
        inst = SyntaxLineSpans()
        inst._lines = self._lines
        inst._tree = self._tree
        inst._query = self._query
        inst._highlighted_blocks = self._highlighted_blocks.copy()
        inst._highlights = self._highlights.copy()
        return inst

    def set_snapshot(
        self, lines: list[str], query: Query, tree: Tree,
    ) -> None:
        """Set the snapshot information for this mapping

        Args:
            lines: The lines from which the syntax tree was generated.
            query: The current Query structure used to generate highlights.
            tree: The tree-sitter syntax tree.
            tab_size: The tab_size for the text area.
        ."""
        if self._tree is not tree:
            self._highlights.clear()
            self._highlighted_blocks.clear()
            self._query = query
            self._tree = tree
            self._lines = [] if None in (query, tree) else lines

    def set_query(self, query: Query) -> None:
        """Set the Query for this `SyntaxLineSpans`."""
        self._query = query
        self._highlights.clear()
        self._highlighted_blocks.clear()

    def __getitem__(self, index: int) -> list[InlineSyntaxItem]:
        if index >= self.line_count:
            return []

        block_index = index // self.BLOCK_SIZE
        if block_index not in self._highlighted_blocks:
            self._highlighted_blocks.add(block_index)
            self._build_part_of_highlight_map(block_index * self.BLOCK_SIZE)
        return self._highlights[index]

    def _build_part_of_highlight_map(self, start_index: int) -> None:
        """Build part of the highlight map.

        This is invoked by __getitem__, when an uncached highlight list is
        accessed. It generates the highlights for the block of lines containing
        the index and adds them to the cache.

        :start_index:
            The start of the block of lines for which to build the map.
        """
        # pylint: disable=too-many-locals
        start_time = time.time()
        start_point = (start_index, 0)
        end_index = min(self.line_count, start_index + self.BLOCK_SIZE)
        end_point = (end_index, 0)
        self._query.set_point_range((start_point, end_point))
        captures = self._query.captures(self._tree.root_node)

        line_count = len(self._lines)
        for highlight_name, nodes in captures.items():
            for node in nodes:
                node_start_row, node_start_column = node.start_point
                node_end_row, node_end_column = node.end_point
                if node_start_row == node_end_row:
                    if node_start_row < line_count:
                        highlight = (
                            node_start_column, node_end_column, highlight_name)
                        self._highlights[node_start_row].append(highlight)
                else:
                    # Add the first line of the node range
                    if node_start_row < line_count:
                        self._highlights[node_start_row].append(
                            (node_start_column, TO_END_OF_LINE, highlight_name)
                        )

                    # Add the middle lines - entire row of this node is
                    # highlighted
                    middle_highlight = (0, TO_END_OF_LINE, highlight_name)
                    for node_row in range(node_start_row + 1, node_end_row):
                        if node_row < line_count:
                            self._highlights[node_row].append(middle_highlight)

                    # Add the last line of the node range
                    if node_end_row < line_count:
                        self._highlights[node_end_row].append(
                            (0, node_end_column, highlight_name)
                        )

        def realign_highlight(highlight):
            start, end, name = highlight
            return mapper[start], mapper[end], name

        # Tree-sitter uses byte offsets, but we want to use characters so we
        # adjust each highlight's offset here to match character (codepoint)
        # positions.
        block_end = min(line_count, start_index + self.BLOCK_SIZE)
        for index in range(start_index, block_end):
            # text, offsets = expand_tabs(self._lines[index])
            text = self._lines[index]
            mapper = build_byte_to_codeppoint_table(text)
            self._highlights[index][:] = [
                realign_highlight(highlight)
                for highlight in self._highlights[index]
            ]

        # The highlights for each line are sorted by start index and then end
        # index. This is sensible order for applying syntax highlighting.
        for line_index in range(start_index, end_index):
            if line_index not in self._highlights:
                continue
            self._highlights[line_index].sort(key=lambda h: h[:2])

        # Remove any highlights that are totally obscured by later highlights.
        for line_index in range(start_index, end_index):
            if line_index not in self._highlights:
                continue
            new = []
            highlights = self._highlights[line_index]
            for a, b, name in reversed(highlights):
                for c, d, _ in new:
                    if c <= a <= d and c <= b <= d:
                        break
                else:
                    new.append((a, b, name))
            highlights[:] = new

        self.times.append(time.time() - start_time)


class IndexMapping(Protocol):
    """A type that maps ints to ints."""

    def __getitem__(self, index: int) -> int:
        ...


class IndexMapper(IndexMapping):
    """An infinite list-like mapping from one index to another."""

    def __init__(self, base_map: MutableSequence[int]):
        self._base_map = base_map or [0]

    def __getitem__(self, index: int) -> int:
        try:
            return self._base_map[index]
        except IndexError:
            return self._base_map[-1] + index - len(self._base_map) + 1


class _IdentityIndexMapper(IndexMapping):
    """A `Mapper` that maps 0->0, 1->1, ..."""

    def __getitem__(self, index: int) -> int:
        return index


@lru_cache(128)
def build_byte_to_codeppoint_table(text: str) -> IndexMapping:
    """Build a mapping of utf-8 byte offsets to UTF-8 codepoints.

    Args:
        text: The string to map.
        tab_size: The size setting to use for TAB expansion.

    Returns:
        A list-like object mapping byte index to character index.
    """
    if not text:
        return identity_index_mapper

    data = text.encode("utf-8")
    if len(data) == len(text):
        return identity_index_mapper

    offsets: MutableSequence[int] = array("L")
    char_offset = 0
    for c in text:
        offsets.append(char_offset)
        ord_c = ord(c)
        if ord_c >= 0x80:
            offsets.append(char_offset)
            if ord_c >= 0x800:
                offsets.append(char_offset)
                if ord_c >= 0x10000:
                    offsets.append(char_offset)
        char_offset += 1

    return IndexMapper(offsets)


identity_index_mapper = _IdentityIndexMapper()
