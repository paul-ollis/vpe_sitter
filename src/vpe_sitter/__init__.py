"""Provide core support for the use of Tree-sitter parse trees.

This plugin maintains a Tree-sitter parse tree for each buffer that
has a supported language.
"""

import vpe
from vpe import vim

from vpe_sitter import listen, parsers


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


class Plugin(vpe.CommandHandler):
    """The plug-in."""

    def __init__(self):
        # create_text_prop_types()
        self.auto_define_commands()

    @vpe.CommandHandler.command('Treesit')
    def run(self):
        """Execute the Treesit command."""
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


app = Plugin()


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
