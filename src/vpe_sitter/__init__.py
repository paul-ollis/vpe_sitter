"""Provide core support for the use of Tree-sitter parse trees.

This plugin maintains a Tree-sitter parse tree for each buffer that
has a supported language.
"""

import vpe
from vpe import vim

from vpe_sitter import listen, parsers


def treesit_current_buffer() -> bool:
    """Start running Tree-sitter on the current buffer.

    Tree-sitter information (`Struct`) is attached to the buffer's store. A

    :return:
        ``True`` if Tree-sitter parsing was succesfully set up for the buffer.
    """
    buf = vim.current.buffer
    if vim.options.encoding != 'utf-8':
        # Currently, I think, UTF-8 encoded text is required.
        print(f'Cannot run Tree-sitter on {buf.options.encoding} text.')
        return False

    parser = parsers.provide_parser(buf.options.filetype)
    if parser is None:
        # No Tree-sitter support available.
        return False

    print(f'Can parse {buf.options.filetype}')
    print(f'   {parser=}')
    print(f'   {parser.language=}')

    query = parsers.provide_query_for_language(buf.options.filetype)
    print(f'   {query=}')
    store = buf.store('tree-sitter')
    store.listener = listen.Listener(buf, parser, query)

    st = '%1*%<%5*%n: %f %1* %2*%m%1*%R%=%4*%15'
    st += '{Cur_prop()}'
    st += '%1* %3*%y%1* W=%{winwidth(0)} %8(%lx%c%) %P'
    vim.current.window.options.statusline = st

    return True


class Plugin(vpe.CommandHandler):
    """The plug-in."""

    def __init__(self):
        # create_text_prop_types()
        self.auto_define_commands()

    @vpe.CommandHandler.command('Treesit')
    def run(self):
        """Execute the Treesit command."""
        treesit_current_buffer()

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
    for prop in props
        let pcol = prop['col']
        let plen = prop['length']
        if pcol <= col && (pcol + plen) > col
            return get(prop, 'type', '-')
        endif
    endfor
    return ''
endfunction
"""

vim.command(_CUR_PROP)
