"""Python specific syntax aware support."""


import functools
from typing import Dict, Tuple

import vpe

from . import init as init_subfiletype
from ..listen import Handler, Highlighter, SubBuffer

hl_map = {
    '!': None,
    '!=': None,
    '!~': None,
    '#': None,
    '$': None,
    '%': None,
    '%=': None,
    '&': None,
    '&&': None,
    "'": None,
    '(': None,
    ')': None,
    '*': None,
    '*=': None,
    '+': None,
    '++nested': None,
    '++once': None,
    '+=': None,
    ',': None,
    '-': None,
    '-=': None,
    '->': None,
    '.': None,
    '..': None,
    '.=': None,
    '/': None,
    '/=': None,
    ':': None,
    ';': None,
    '<': None,
    '<=': None,
    '<buffer>': None,
    '<expr>': None,
    '<nowait>': None,
    '<script>': None,
    '<silent>': None,
    '<unique>': None,
    '=': None,
    '==': None,
    '=~': None,
    '>': None,
    '>=': None,
    '?': None,
    '@': None,
    'ALL': None,
    'NONE': None,
    'OPT': None,
    'PACK': None,
    'START': None,
    '[': None,
    '\\': None,
    '\\%(': None,
    '\\&': None,
    '\\(': None,
    '\\)': None,
    '\\/': None,
    '\\?': None,
    '\\z(': None,
    '\\|': None,
    ']': None,
    '^=': None,
    'a:': None,
    'abort': None,
    'add': None,
    'all': None,
    'all&': None,
    'ansi': None,
    'argument': None,
    'arguments': None,
    'at': None,
    'au_event': None,
    'au_event_list': None,
    'augroup': None,
    'augroup_name': None,
    'augroup_statement': None,
    'autocmd': None,
    'autocmd_statement': None,
    'background': None,
    'bang': None,
    'bang_filter_statement': None,
    'bangs': None,
    'bg': None,
    'big5': None,
    'binary_operation': None,
    'body': None,
    'bold': None,
    'buffer': None,
    'call': None,
    'call_expression': None,
    'call_statement': None,
    'case': None,
    'catch': None,
    'catch_statement': None,
    'cchar': None,
    'ccomment': None,
    'chinese': None,
    'chunk': None,
    'clear': None,
    'closure': None,
    'cluster': None,
    'cmap': None,
    'cnoremap': None,
    'colorscheme': None,
    'colorscheme_statement': None,
    'comclear': None,
    'comclear_statement': None,
    'command': None,
    'command_argument': None,
    'command_name': None,
    'commands': None,
    'comment': 'Comment',
    'conceal': None,
    'concealends': None,
    'const': None,
    'const_statement': None,
    'contained': None,
    'containedin': None,
    'contains': None,
    'cp1250': None,
    'cp1251': None,
    'cp1253': None,
    'cp1254': None,
    'cp1255': None,
    'cp1256': None,
    'cp1257': None,
    'cp1258': None,
    'cp437': None,
    'cp737': None,
    'cp775': None,
    'cp850': None,
    'cp852': None,
    'cp855': None,
    'cp857': None,
    'cp860': None,
    'cp861': None,
    'cp862': None,
    'cp863': None,
    'cp865': None,
    'cp866': None,
    'cp869': None,
    'cp874': None,
    'cp932': None,
    'cp936': None,
    'cp949': None,
    'cp950': None,
    'cterm': None,
    'ctermbg': None,
    'ctermfg': None,
    'culhl': None,
    'curly_braces_name': None,
    'current_line': None,
    'default': None,
    'default_option': None,
    'default_parameter': None,
    'define': None,
    'delcommand': None,
    'delcommand_statement': None,
    'detect': None,
    'dict': None,
    'dictionnary': None,
    'dictionnary_entry': None,
    'display': None,
    'echo': None,
    'echo_statement': None,
    'echoerr': None,
    'echoerr_statement': None,
    'echohl': None,
    'echohl_statement': None,
    'echomsg': None,
    'echomsg_statement': None,
    'echon': None,
    'echon_statement': None,
    'else': None,
    'else_statement': None,
    'elseif': None,
    'elseif_statement': None,
    'enable': None,
    'encoding': None,
    'end': None,
    'endfor': None,
    'endfunction': None,
    'endif': None,
    'endtry': None,
    'endwhile': None,
    'env_variable': None,
    'euc-cn': None,
    'euc-jp': None,
    'euc-kr': None,
    'euc-tw': None,
    'excludenl': None,
    'execute': None,
    'execute_statement': None,
    'extend': None,
    'fg': None,
    'field_expression': None,
    'file': None,
    'filename': None,
    'filenames': None,
    'filetype': None,
    'filetype_statement': None,
    'filter_command': None,
    'finally': Exception,
    'finally_statement': None,
    'float_literal': 'Float',
    'fold': None,
    'foldlevel': None,
    'font': None,
    'for': 'Repeat',
    'for_loop': 'Repeat',
    'foreground': None,
    'fromstart': None,
    'function': 'Function',
    'function_declaration': None,
    'function_definition': None,
    'global': None,
    'global_statement': None,
    'group': None,
    'grouphere': None,
    'groupthere': None,
    'gui': None,
    'guibg': None,
    'guifg': None,
    'guisp': None,
    'he': None,
    'highlight': None,
    'highlight_statement': None,
    'hl_attribute': None,
    'hl_group': None,
    'hl_groups': None,
    'hs': None,
    'icon': None,
    'identifier': 'Identifier',
    'if': 'Conditional',
    'if_statement': None,
    'ignore': None,
    'imap': None,
    'in': None,
    'include': None,
    'indent': None,
    'index_expression': None,
    'inoremap': None,
    'integer_literal': 'Number',
    'inv_option': None,
    'inverse': None,
    'is': 'Conditional',
    'iskeyword': None,
    'isnot': 'Conditional',
    'iso': None,
    'italic': None,
    'japan': None,
    'jump': None,
    'keepend': None,
    'keycode': None,
    'keyword': None,
    'koi8': None,
    'korea': None,
    'lambda_expression': None,
    'last_line': None,
    'latin1': None,
    'lc': None,
    'let': None,
    'let_statement': 'Statement',
    'line': None,
    'linebreaks': None,
    'linecont': None,
    'linehl': None,
    'lines': None,
    'link': None,
    'list': None,
    'list_assignment': None,
    'lmap': None,
    'lnoremap': None,
    'lua': None,
    'lua_statement': None,
    'macroman': None,
    'map': None,
    'map_side': None,
    'map_statement': None,
    'mark': None,
    'match': None,
    'match_case': None,
    'matchgroup': None,
    'maxlines': None,
    'me': None,
    'minimum': None,
    'minlines': None,
    'ms': None,
    'name': None,
    'next_line': None,
    'nextgroup': None,
    'nmap': None,
    'nnoremap': None,
    'no_option': None,
    'nocombine': None,
    'noremap': None,
    'normal': None,
    'normal_statement': None,
    'notoplevel': None,
    'numhl': None,
    'off': None,
    'omap': None,
    'on': None,
    'oneline': None,
    'onoremap': None,
    'option': None,
    'option_name': 'PreProc',
    'parameters': None,
    'pattern': None,
    'pattern_multi': None,
    'pattern_offset': None,
    'perl': None,
    'perl_statement': None,
    'place': None,
    'plugin': None,
    'prc': None,
    'previous_pattern': None,
    'priority': None,
    'python': None,
    'python_statement': None,
    'range': None,
    'range_statement': None,
    're': None,
    'region': None,
    'register': None,
    'register_statement': None,
    'remove': None,
    'reset': None,
    'return': None,
    'return_statement': None,
    'reverse': None,
    'rs': None,
    'ruby': None,
    'ruby_statement': None,
    'runtime': None,
    'runtime_statement': None,
    'scope': None,
    'scope_dict': None,
    'scoped_identifier': None,
    'script': None,
    'script_file': None,
    'scriptencoding': None,
    'scriptencoding_statement': None,
    'set': None,
    'set_item': None,
    'set_statement': None,
    'set_value': None,
    'setlocal': None,
    'setlocal_statement': None,
    'sign': None,
    'sign_argument': None,
    'sign_statement': None,
    'silent': None,
    'silent_statement': None,
    'sjis': None,
    'skip': None,
    'skipempty': None,
    'skipnl': None,
    'skipwhite': None,
    'slice_expression': None,
    'smap': None,
    'snoremap': None,
    'source': None,
    'source_statement': None,
    'spell': None,
    'spread': None,
    'standout': None,
    'start': None,
    'startinsert': None,
    'startinsert_statement': None,
    'state': None,
    'stop': None,
    'stopinsert': None,
    'stopinsert_statement': None,
    'strikethrough': None,
    'string_literal': 'String',
    'sync': None,
    'syntax': None,
    'syntax_argument': None,
    'syntax_statement': None,
    't_': None,
    'taiwan': None,
    'ternary_expression': None,
    'text': None,
    'texthl': None,
    'throw': Exception,
    'throw_statement': None,
    'tmap': None,
    'tnoremap': None,
    'toplevel': None,
    'transparent': None,
    'try': Exception,
    'try_statement': None,
    'ucs-2': None,
    'ucs-21e': None,
    'ucs-2be': None,
    'ucs-4': None,
    'ucs-4be': None,
    'ucs-4le': None,
    'ucs2be': None,
    'unary_operation': None,
    'undefine': None,
    'undercurl': None,
    'underline': None,
    'unicode': None,
    'unknown_builtin_statement': None,
    'unknown_command_name': None,
    'unlet': None,
    'unlet_statement': None,
    'unplace': None,
    'user_command': None,
    'utf-16': None,
    'utf-16le': None,
    'utf-32': None,
    'utf-32le': None,
    'utf-8': None,
    'utf8': None,
    'value': None,
    'vi': None,
    'vim': None,
    'vmap': None,
    'vnoremap': None,
    'where': None,
    'while': 'Repeat',
    'while_loop': 'Repeat',
    'wildcard': None,
    'wincmd': None,
    'wincmd_statement': None,
    'xmap': None,
    'xnoremap': None,
    '{': None,
    '||': None,
    '}': None,
}

keywords = '''
    a ab abclear aboveleft abstract addd all argadd argdedupe argdelete argdo
    argedit argglobal arglocal args argument ascii au badd ball balt bdelete
    belowright bfirst blast bmodified bnext bNext botright bprevious break
    breakadd breakdel breaklist brewind browse bufdo buffer buffers bunload
    bwipeout ca cabclear cabove caddbuffer caddexpr caddfile cafter call catch
    cbefore cbelow cbottom cbuffer cc cclose cd cdo center cexpr cfdo cfile
    cfirst cgetbuffer cgetexpr cgetfile change changes chdir checkpath
    checktime chistory class clast clearjumps clist close cmapclear cnewer
    cnext cNext cnfile cNfile cnor colder colorscheme com comclear compiler
    confirm const continue copen copy cpfile cprevious cquit crewind cs cscope
    cstag cun cunabbrev cwindow debug debuggreedy def defcompile delcommand
    delel delep delete deletel deletep deletl deletp delfunction dell delmarks
    delp dep diffget diffoff diffpatch diffput diffsplit diffthis diffupdate
    digraphs dir disassemble display djump dl dlist do doau doaut dp drop
    dsearch dsplit ea earlier ec echoconsole echoerr echomsg echon edit else
    elseif emenu endclass enddef endenum endfor endfunction endif endinterface
    endtry endwhile enew enum eval ex exit exp export exusage file files filet
    filetype filter finally find finish first fixdel fold foldclose
    folddoclosed folddoopen foldopen for function g goto grep grepadd gui gvim
    hardcopy help helpclose helpfind helpgrep helptags hi hide history i ia
    iabclear if ijump ilist imapclear imp import in inor interface intro
    isearch isplit iunabbrev join jumps k keepa keepalt keepjumps keepmarks
    keeppatterns labove laddbuffer laddexpr laddfile lafter language last lat
    later lbefore lbelow lbottom lbuffer lcd lchdir lclose lcs lcscope ldo left
    leftabove legacy lexpr lfdo lfile lfirst lgetbuffer lgetexpr lgetfile lgrep
    lgrepadd lhelpgrep lhistory list ll llast llist lma lmake lmapclear lnewer
    lnext lNext lnfile lNfile loadk loadkeymap loadview lockmarks lockvar
    lolder lopen lpfile lprevious lrewind ls ltag lua luado luafile lvimgrep
    lvimgrepadd lwindow make mark marks match menutranslate messages mkexrc
    mksession mkspell mkview mkvimrc mode move mzfile mzscheme nbclose nbkey
    nbstart new next nmapclear noa noautocmd nohlsearch nor nore noswapfile
    number oldfiles omapclear only open options ownsyntax packadd packloadall
    pclose pedit perl perldo pop popup ppop preserve previous print pro profdel
    profile promptfind promptrepl psearch ptag ptfirst ptjump ptlast ptnext
    ptNext ptprevious ptrewind ptselect put pwd py3 py3do py3file py3file pydo
    pyfile python python3 pythonx pyx pyxdo pyxfile qall quit quitall read
    recover redir redo redraw redrawstatus redrawtabline registers resize retab
    return rewind right rightbelow ruby rubydo rubyfile rundo runtime rviminfo
    sall sandbox sargument saveas sball sbfirst sblast sbmodified sbnext sbNext
    sbprevious sbrewind sbuffer sc sce scg sci scI scl scp scriptencoding
    scriptnames scriptversion scs scscope set setfiletype setglobal setlocal
    sfind sfirst sg sgc sge sgi sgI sgl sgn sgp sgr shell si sI sic sIc sie sIe
    sig sIg sign sIl silent simalt sin sIn sip sIp sir sIr slast sleep smagic
    smap sme smenu smile snext sNext snomagic snoreme snoremenu sort source
    spelldump spellgood spellinfo spellrare spellrepall spellrrare spellundo
    spellwrong split sprevious sr src srewind srg sri srI srl srn srp stag
    startgreplace startinsert startreplace static stjump stop stopinsert
    stselect substitutepattern substituterepeat sunhide sunme sunmenu suspend
    sview swapname sy syn sync syncbind syntime t tab tabclose tabdo tabedit
    tabfind tabfirst tablast tabmove tabnew tabnext tabNext tabonly tabprevious
    tabrewind tabs tag tags tcd tchdir tcl tcldo tclfile tearoff terminal
    tfirst throw tjump tlast tlm tlmenu tln tlnoremenu tlu tlunmenu tmap
    tmapclear tmenu tnext tNext tnoremap topleft tprevious trewind try tselect
    tunmap tunmenu type unabbreviate undo undojoin undolist unhide unl
    unlockvar unsilent update v var verbose version vertical view vim9cmd
    vim9script vimgrep vimgrepadd visual viusage vnew vsplit wall while wincmd
    windo winpos winsize wnext wNext wprevious wq wqall write wundo wviminfo
    xall xit xmapclear xme xmenu xnoreme xnoremenu xprop xrestore xunme xunmenu
    xwininfo yank'''

for kw in keywords.split():
    if kw in hl_map:
        hl_map[kw] = 'Keyword'

log = functools.partial(vpe.call_soon, print)


class VimScriptHandler(Handler):
    handler_switch_table: Dict[Tuple[str, str], str] = {
        ('*', 'python_statement'):     'VimPythonStatementHandler',
    }


class VimPythonStatementHandler(Handler):
    handler_switch_table: Dict[Tuple[str, str], str] = {
        ('*', 'script'):     'VimPythonScriptHandler',
    }

    def should_descend(self):
        if self.event != 'script':
            return True

        info = init_subfiletype('python')
        node = self.node
        a, b = node.start_point
        c, d = node.end_point
        sub_buffer = SubBuffer(self.buf.buf, a + 1, c)
        log_range = self.highlighter.log_range
        if log_range is not None:
            log_range = range(log_range.start - a - 1, log_range.stop - a - 1)
        highlighter = Highlighter(self.buf.buf, sub_buffer, info)
        highlighter.log_range = log_range
        highlighter.dry_run = self.highlighter.dry_run
        highlighter.init_run()


class VimPythonScriptHandler(Handler):
    handler_switch_table: Dict[Tuple[str, str], str] = {
    }


root_handler_type = VimScriptHandler
lang_name = 'vim'
source_name = 'viml'
