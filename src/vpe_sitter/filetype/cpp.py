"""C code specific syntax aware support."""


import functools
from typing import Dict, Tuple

import vpe

from . import init as init_subfiletype
from ..listen import Handler, Highlighter, SubBuffer


hilinks = {
    'cBadContinuation': 'Error',
    'cCharacter': 'Character',
    'cComment2String': 'cString',
    'cComment': 'Comment',
    'cCommentError': 'cError',
    'cCommentL': 'cComment',
    'cCommentSkip': 'cComment',
    'cCommentStart': 'cComment',
    'cCommentStartError': 'cError',
    'cCommentString': 'cString',
    'cConditional': 'Conditional',
    'cConstant': 'Constant',
    'cCppInElse2': 'cCppOutIf2',
    'cCppInWrapper': 'cCppOutWrapper',
    'cCppOut': 'Comment',
    'cCppOutIf2': 'cCppOut',
    'cCppOutSkip': 'cCppOutIf2',
    'cCppOutWrapper': 'cPreCondit',
    'cCppString': 'cString',
    'cCurlyError': 'cError',
    'cDefine': 'Macro',
    'cErrInBracket': 'cError',
    'cErrInParen': 'cError',
    'cError': 'Error',
    'cFloat': 'Float',
    'cFormat': 'cSpecial',
    'cIncluded': 'cString',
    'cInclude': 'Include',
    'cLabel': 'Label',
    'cNumber': 'Number',
    'cOctalError': 'cError',
    'cOctal': 'Number',
    'cOctalZero': 'PreProc',
    'cOperator': 'Operator',
    'cParenError': 'cError',
    'cPreConditMatch': 'cPreCondit',
    'cPreCondit': 'PreCondit',
    'cPreProc': 'PreProc',
    'cRepeat': 'Repeat',
    'cSpaceError': 'cError',
    'cSpecialCharacter': 'cSpecial',
    'cSpecialError': 'cError',
    'cSpecial': 'SpecialChar',
    'cStatement': 'Statement',
    'cStorageClass': 'StorageClass',
    'cString': 'String',
    'cStructure': 'Structure',
    'cTodo': 'Todo',
    'cTypedef': 'Structure',
    'cType': 'Type',
    'cUserLabel': 'Label',
    'cWrongComTail': 'cError',
}

def resolve(grp):
    if grp not in hilinks:
        return grp
    else:
        return resolve(hilinks[grp])


links = {}
for grp, linked_grp in hilinks.items():
    links[grp] = resolve(linked_grp)

hl_map = {
    'comment': links['cComment'],
    # 'preproc_ifdef': links['cPreCondit'],
    '#endif': links['cPreCondit'],
    'preproc_def': links['cDefine'],
    'preproc_arg': links['cStatement'],

#   syn keyword	cStatement	goto break return continue asm
#   syn keyword	cLabel		case default
#   syn keyword	cConditional	if else switch
#   syn keyword	cRepeat		while for do
#   syn keyword	cTodo		contained TODO FIXME XXX
#   syn cluster	cCommentGroup	contains=cTodo,cBadContinuation
#   syn match	cSpecial	display contained "\\\%(x\x\+\|\o\{1,3}\|.\|$\)"
#   syn match	cSpecial	display contained "\\\%(u\x\{4}\|U\x\{8}\)"
#   syn match	cFormat		display "%\%(\d\+\$\)\=[-+' #0*]*\%(\d*\|\*\|\*\d\+\$\)\%(\.\%(\d*\|\*\|\*\d\+\$\)\)\=\%([hlLjzt]\|ll\|hh\)\=\%([aAbdiuoxXDOUfFeEgGcCsSpn]\|\[\^\=.[^]]*\]\)" contained
#   syn match	cFormat		display "%%" contained
#   syn region	cString		start=+\%(L\|u\|u8\|U\|R\|LR\|u8R\|uR\|UR\)\="+ skip=+\\\\\|\\"+ end=+"+ contains=cSpecial,cFormat,@Spell extend
#   syn region 	cCppString	start=+\%(L\|u\|u8\|U\|R\|LR\|u8R\|uR\|UR\)\="+ skip=+\\\\\|\\"\|\\$+ excludenl end=+"+ end='$' contains=cSpecial,cFormat,@Spell
#   syn region	cCppSkip	contained start="^\s*\%(%:\|#\)\s*\%(if\>\|ifdef\>\|ifndef\>\)" skip="\\$" end="^\s*\%(%:\|#\)\s*endif\>" contains=cSpaceError,cCppSkip
#   syn cluster	cStringGroup	contains=cCppString,cCppSkip
#   syn match	cCharacter	"L\='[^\\]'"
#   syn match	cCharacter	"L'[^']*'" contains=cSpecial
#   syn match	cSpecialError	"L\='\\[^'\"?\\abefnrtv]'"
#   syn match	cSpecialCharacter "L\='\\['\"?\\abefnrtv]'"
#   syn match	cSpecialCharacter display "L\='\\\o\{1,3}'"
#   syn match	cSpecialCharacter display "'\\x\x\{1,2}'"
#   syn match	cSpecialCharacter display "L'\\x\x\+'"
#   syn region	cString		start=+\%(U\|u8\=\)"+ skip=+\\\\\|\\"+ end=+"+ contains=cSpecial,@Spell extend
#   syn match	cCharacter	"[Uu]'[^\\]'"
#   syn match	cCharacter	"[Uu]'[^']*'" contains=cSpecial
#   syn match	cSpecialError	"[Uu]'\\[^'\"?\\abefnrtv]'"
#   syn match	cSpecialCharacter "[Uu]'\\['\"?\\abefnrtv]'"
#   syn match	cSpecialCharacter display "[Uu]'\\\o\{1,3}'"
#   syn match	cSpecialCharacter display "[Uu]'\\x\x\+'"
#   syn match	cSpaceError	display excludenl "\s\+$"
#   syn region	cBlock		start="{" end="}" contains=ALLBUT,cBadBlock,cCurlyError,@cParenGroup,cErrInParen,cCppParen,cErrInBracket,cCppBracket,@cStringGroup,@Spell fold
#   syn cluster	cParenGroup	contains=cParenError,cIncluded,cSpecial,cCommentSkip,cCommentString,cComment2String,@cCommentGroup,cCommentStartError,cUserLabel,cBitField,cOctalZero,@cCppOutInGroup,cFormat,cNumber,cFloat,cOctal,cOctalError,cNumbersCom
#   syn region	cParen		transparent start='(' end=')' contains=ALLBUT,@cParenGroup,cCppParen,@cStringGroup,@Spell
#   syn region	cCppParen	transparent start='(' skip='\\$' excludenl end=')' end='$' contained contains=ALLBUT,@cParenGroup,cParen,cString,@Spell
#   syn match	cParenError	display ")"
#   syn match	cErrInParen	display contained "^^<%\|^%>"
#   syn region	cBadBlock	keepend start="{" end="}" contained containedin=cParen,cBracket,cBadBlock transparent fold
#   syn case ignore
#   syn match	cNumbers	display transparent "\<\d\|\.\d" contains=cNumber,cFloat,cOctalError,cOctal
#   syn match	cNumbersCom	display contained transparent "\<\d\|\.\d" contains=cNumber,cFloat,cOctal
#   syn match	cNumber		display contained "\d\+\%(u\=l\{0,2}\|ll\=u\)\>"
#   syn match	cNumber		display contained "0x\x\+\%(u\=l\{0,2}\|ll\=u\)\>"
#   syn match	cOctal		display contained "0\o\+\%(u\=l\{0,2}\|ll\=u\)\>" contains=cOctalZero
#   syn match	cOctalZero	display contained "\<0"
#   syn match	cFloat		display contained "\d\+\.\d*\%(e[-+]\=\d\+\)\=[fl]\="
#   syn match	cFloat		display contained "\.\d\+\%(e[-+]\=\d\+\)\=[fl]\=\>"
#   syn match	cFloat		display contained "\d\+e[-+]\=\d\+[fl]\=\>"
#   syn match	cFloat		display contained "0x\x*\.\x\+p[-+]\=\d\+[fl]\=\>"
#   syn match	cFloat		display contained "0x\x\+\.\=p[-+]\=\d\+[fl]\=\>"
#   syn match	cOctalError	display contained "0\o*[89]\d*"
#   syn case match
#   syn match	cCommentSkip	contained "^\s*\*\%($\|\s\+\)"
#   syn region cCommentString	contained start=+L\=\\\@<!"+ skip=+\\\\\|\\"+ end=+"+ end=+\*/+me=s-1 contains=cSpecial,cCommentSkip
#   syn region cComment2String	contained start=+L\=\\\@<!"+ skip=+\\\\\|\\"+ end=+"+ end="$" contains=cSpecial
#   syn region  cCommentL	start="//" skip="\\$" end="$" keepend contains=@cCommentGroup,cComment2String,cCharacter,cNumbersCom,cSpaceError,cWrongComTail,@Spell
#   syn region cComment	matchgroup=cCommentStart start="/\*" end="\*/" contains=@cCommentGroup,cCommentStartError,cCommentString,cCharacter,cNumbersCom,cSpaceError,@Spell extend
#   syn region cComment	matchgroup=cCommentStart start="/\*" end="\*/" contains=@cCommentGroup,cCommentStartError,cCommentString,cCharacter,cNumbersCom,cSpaceError,@Spell fold extend
#   syn region	cCommentL	start="//" skip="\\$" end="$" keepend contains=@cCommentGroup,cSpaceError,@Spell
#   syn region	cComment	matchgroup=cCommentStart start="/\*" end="\*/" contains=@cCommentGroup,cCommentStartError,cSpaceError,@Spell extend
#   syn region	cComment	matchgroup=cCommentStart start="/\*" end="\*/" contains=@cCommentGroup,cCommentStartError,cSpaceError,@Spell fold extend
#   syn match	cCommentError	display "\*/"
#   syn match	cCommentStartError display "/\*"me=e-1 contained
#   syn match	cWrongComTail	display "\*/"
#   syn keyword	cOperator	sizeof
#   syn keyword	cType		__label__ __complex__
#   syn keyword	cStatement	__asm__
#   syn keyword	cOperator	__alignof__
#   syn keyword	cOperator	typeof __typeof__
#   syn keyword	cOperator	__real__ __imag__
#   syn keyword	cStorageClass	__attribute__ __const__ __extension__
#   syn keyword	cStorageClass	inline __inline__
#   syn keyword	cStorageClass	__restrict__ __volatile__ __noreturn__
#   syn keyword	cType		int long short char void
#   syn keyword	cType		signed unsigned float double
#   syn keyword   cType		size_t ssize_t off_t wchar_t ptrdiff_t sig_atomic_t fpos_t
#   syn keyword   cType		clock_t time_t va_list jmp_buf FILE DIR div_t ldiv_t
#   syn keyword   cType		mbstate_t wctrans_t wint_t wctype_t
#   syn keyword	cType		_Bool bool _Complex complex _Imaginary imaginary
#   syn keyword	cType		int8_t int16_t int32_t int64_t
#   syn keyword	cType		uint8_t uint16_t uint32_t uint64_t
#   syn keyword	cType		u_int8_t u_int16_t u_int32_t u_int64_t
#   syn keyword	cType		int_least8_t int_least16_t int_least32_t int_least64_t
#   syn keyword	cType		uint_least8_t uint_least16_t uint_least32_t uint_least64_t
#   syn keyword	cType		int_fast8_t int_fast16_t int_fast32_t int_fast64_t
#   syn keyword	cType		uint_fast8_t uint_fast16_t uint_fast32_t uint_fast64_t
#   syn keyword	cType		intptr_t uintptr_t
#   syn keyword	cType		intmax_t uintmax_t
#   syn keyword	cTypedef	typedef
#   syn keyword	cStructure	struct union enum
#   syn keyword	cStorageClass	static register auto volatile extern const
#   syn keyword	cStorageClass	inline restrict
#   syn keyword	cStorageClass	_Alignas alignas
#   syn keyword	cOperator	_Alignof alignof
#   syn keyword	cStorageClass	_Atomic
#   syn keyword	cOperator	_Generic
#   syn keyword	cStorageClass	_Noreturn noreturn
#   syn keyword	cOperator	_Static_assert static_assert
#   syn keyword	cStorageClass	_Thread_local thread_local
#   syn keyword   cType		char16_t char32_t
#   syn keyword   cType		max_align_t
#   syn keyword	cType		atomic_bool atomic_char atomic_schar atomic_uchar
#   syn keyword	Ctype		atomic_short atomic_ushort atomic_int atomic_uint
#   syn keyword	cType		atomic_long atomic_ulong atomic_llong atomic_ullong
#   syn keyword	cType		atomic_char16_t atomic_char32_t atomic_wchar_t
#   syn keyword	cType		atomic_int_least8_t atomic_uint_least8_t
#   syn keyword	cType		atomic_int_least16_t atomic_uint_least16_t
#   syn keyword	cType		atomic_int_least32_t atomic_uint_least32_t
#   syn keyword	cType		atomic_int_least64_t atomic_uint_least64_t
#   syn keyword	cType		atomic_int_fast8_t atomic_uint_fast8_t
#   syn keyword	cType		atomic_int_fast16_t atomic_uint_fast16_t
#   syn keyword	cType		atomic_int_fast32_t atomic_uint_fast32_t
#   syn keyword	cType		atomic_int_fast64_t atomic_uint_fast64_t
#   syn keyword	cType		atomic_intptr_t atomic_uintptr_t
#   syn keyword	cType		atomic_size_t atomic_ptrdiff_t
#   syn keyword	cType		atomic_intmax_t atomic_uintmax_t
#   syn keyword cConstant __GNUC__ __FUNCTION__ __PRETTY_FUNCTION__ __func__
#   syn keyword cConstant __LINE__ __FILE__ __DATE__ __TIME__ __STDC__ __STDC_VERSION__ __STDC_HOSTED__
#   syn keyword cConstant CHAR_BIT MB_LEN_MAX MB_CUR_MAX
#   syn keyword cConstant UCHAR_MAX UINT_MAX ULONG_MAX USHRT_MAX
#   syn keyword cConstant CHAR_MIN INT_MIN LONG_MIN SHRT_MIN
#   syn keyword cConstant CHAR_MAX INT_MAX LONG_MAX SHRT_MAX
#   syn keyword cConstant SCHAR_MIN SINT_MIN SLONG_MIN SSHRT_MIN
#   syn keyword cConstant SCHAR_MAX SINT_MAX SLONG_MAX SSHRT_MAX
#   syn keyword cConstant __func__ __VA_ARGS__
#   syn keyword cConstant LLONG_MIN LLONG_MAX ULLONG_MAX
#   syn keyword cConstant INT8_MIN INT16_MIN INT32_MIN INT64_MIN
#   syn keyword cConstant INT8_MAX INT16_MAX INT32_MAX INT64_MAX
#   syn keyword cConstant UINT8_MAX UINT16_MAX UINT32_MAX UINT64_MAX
#   syn keyword cConstant INT_LEAST8_MIN INT_LEAST16_MIN INT_LEAST32_MIN INT_LEAST64_MIN
#   syn keyword cConstant INT_LEAST8_MAX INT_LEAST16_MAX INT_LEAST32_MAX INT_LEAST64_MAX
#   syn keyword cConstant UINT_LEAST8_MAX UINT_LEAST16_MAX UINT_LEAST32_MAX UINT_LEAST64_MAX
#   syn keyword cConstant INT_FAST8_MIN INT_FAST16_MIN INT_FAST32_MIN INT_FAST64_MIN
#   syn keyword cConstant INT_FAST8_MAX INT_FAST16_MAX INT_FAST32_MAX INT_FAST64_MAX
#   syn keyword cConstant UINT_FAST8_MAX UINT_FAST16_MAX UINT_FAST32_MAX UINT_FAST64_MAX
#   syn keyword cConstant INTPTR_MIN INTPTR_MAX UINTPTR_MAX
#   syn keyword cConstant INTMAX_MIN INTMAX_MAX UINTMAX_MAX
#   syn keyword cConstant PTRDIFF_MIN PTRDIFF_MAX SIG_ATOMIC_MIN SIG_ATOMIC_MAX
#   syn keyword cConstant SIZE_MAX WCHAR_MIN WCHAR_MAX WINT_MIN WINT_MAX
#   syn keyword cConstant FLT_RADIX FLT_ROUNDS FLT_DIG FLT_MANT_DIG FLT_EPSILON DBL_DIG DBL_MANT_DIG DBL_EPSILON
#   syn keyword cConstant LDBL_DIG LDBL_MANT_DIG LDBL_EPSILON FLT_MIN FLT_MAX FLT_MIN_EXP FLT_MAX_EXP FLT_MIN_10_EXP FLT_MAX_10_EXP
#   syn keyword cConstant DBL_MIN DBL_MAX DBL_MIN_EXP DBL_MAX_EXP DBL_MIN_10_EXP DBL_MAX_10_EXP LDBL_MIN LDBL_MAX LDBL_MIN_EXP LDBL_MAX_EXP
#   syn keyword cConstant LDBL_MIN_10_EXP LDBL_MAX_10_EXP HUGE_VAL CLOCKS_PER_SEC NULL LC_ALL LC_COLLATE LC_CTYPE LC_MONETARY
#   syn keyword cConstant LC_NUMERIC LC_TIME SIG_DFL SIG_ERR SIG_IGN SIGABRT SIGFPE SIGILL SIGHUP SIGINT SIGSEGV SIGTERM
#   syn keyword cConstant SIGABRT SIGALRM SIGCHLD SIGCONT SIGFPE SIGHUP SIGILL SIGINT SIGKILL SIGPIPE SIGQUIT SIGSEGV
#   syn keyword cConstant SIGSTOP SIGTERM SIGTRAP SIGTSTP SIGTTIN SIGTTOU SIGUSR1 SIGUSR2
#   syn keyword cConstant _IOFBF _IOLBF _IONBF BUFSIZ EOF WEOF FOPEN_MAX FILENAME_MAX L_tmpnam
#   syn keyword cConstant SEEK_CUR SEEK_END SEEK_SET TMP_MAX stderr stdin stdout EXIT_FAILURE EXIT_SUCCESS RAND_MAX
#   syn keyword cConstant NDEBUG
#   syn keyword cConstant SIGBUS SIGPOLL SIGPROF SIGSYS SIGURG SIGVTALRM SIGXCPU SIGXFSZ
#   syn keyword cConstant SIGWINCH SIGINFO
#   syn keyword cConstant E2BIG EACCES EADDRINUSE EADDRNOTAVAIL EAFNOSUPPORT EAGAIN EALREADY EBADF
#   syn keyword cConstant EBADMSG EBUSY ECANCELED ECHILD ECONNABORTED ECONNREFUSED ECONNRESET EDEADLK
#   syn keyword cConstant EDESTADDRREQ EDOM EDQUOT EEXIST EFAULT EFBIG EHOSTUNREACH EIDRM EILSEQ
#   syn keyword cConstant EINPROGRESS EINTR EINVAL EIO EISCONN EISDIR ELOOP EMFILE EMLINK EMSGSIZE
#   syn keyword cConstant EMULTIHOP ENAMETOOLONG ENETDOWN ENETRESET ENETUNREACH ENFILE ENOBUFS ENODATA
#   syn keyword cConstant ENODEV ENOENT ENOEXEC ENOLCK ENOLINK ENOMEM ENOMSG ENOPROTOOPT ENOSPC ENOSR
#   syn keyword cConstant ENOSTR ENOSYS ENOTBLK ENOTCONN ENOTDIR ENOTEMPTY ENOTRECOVERABLE ENOTSOCK ENOTSUP
#   syn keyword cConstant ENOTTY ENXIO EOPNOTSUPP EOVERFLOW EOWNERDEAD EPERM EPIPE EPROTO
#   syn keyword cConstant EPROTONOSUPPORT EPROTOTYPE ERANGE EROFS ESPIPE ESRCH ESTALE ETIME ETIMEDOUT
#   syn keyword cConstant ETXTBSY EWOULDBLOCK EXDEV
#   syn keyword cConstant M_E M_LOG2E M_LOG10E M_LN2 M_LN10 M_PI M_PI_2 M_PI_4
#   syn keyword cConstant M_1_PI M_2_PI M_2_SQRTPI M_SQRT2 M_SQRT1_2
#   syn keyword cConstant true false
#   syn region	cPreCondit	start="^\s*\zs\%(%:\|#\)\s*\%(if\|ifdef\|ifndef\|elif\)\>" skip="\\$" end="$" keepend contains=cComment,cCommentL,cCppString,cCharacter,cCppParen,cParenError,cNumbers,cCommentError,cSpaceError
#   syn match	cPreConditMatch	display "^\s*\zs\%(%:\|#\)\s*\%(else\|endif\)\>"
#   syn cluster	cCppOutInGroup	contains=cCppInIf,cCppInElse,cCppInElse2,cCppOutIf,cCppOutIf2,cCppOutElse,cCppInSkip,cCppOutSkip
#   syn region	cCppOutWrapper	start="^\s*\zs\%(%:\|#\)\s*if\s\+0\+\s*\%($\|//\|/\*\|&\)" end=".\@=\|$" contains=cCppOutIf,cCppOutElse,@NoSpell fold
#   syn region	cCppOutIf	contained start="0\+" matchgroup=cCppOutWrapper end="^\s*\%(%:\|#\)\s*endif\>" contains=cCppOutIf2,cCppOutElse
#   syn region	cCppOutIf2	contained matchgroup=cCppOutWrapper start="0\+" end="^\s*\%(%:\|#\)\s*\%(else\>\|elif\s\+\%(0\+\s*\%($\|//\|/\*\|&\)\)\@!\|endif\>\)"me=s-1 contains=cSpaceError,cCppOutSkip,@Spell fold
#   syn region	cCppOutIf2	contained matchgroup=cCppOutWrapper start="0\+" end="^\s*\%(%:\|#\)\s*\%(else\>\|elif\s\+\%(0\+\s*\%($\|//\|/\*\|&\)\)\@!\|endif\>\)"me=s-1 contains=cSpaceError,cCppOutSkip,@Spell
#   syn region	cCppOutElse	contained matchgroup=cCppOutWrapper start="^\s*\%(%:\|#\)\s*\%(else\|elif\)" end="^\s*\%(%:\|#\)\s*endif\>"me=s-1 contains=TOP,cPreCondit
#   syn region	cCppInWrapper	start="^\s*\zs\%(%:\|#\)\s*if\s\+0*[1-9]\d*\s*\%($\|//\|/\*\||\)" end=".\@=\|$" contains=cCppInIf,cCppInElse fold
#   syn region	cCppInIf	contained matchgroup=cCppInWrapper start="\d\+" end="^\s*\%(%:\|#\)\s*endif\>" contains=TOP,cPreCondit
#   syn region	cCppInElse	contained start="^\s*\%(%:\|#\)\s*\%(else\>\|elif\s\+\%(0*[1-9]\d*\s*\%($\|//\|/\*\||\)\)\@!\)" end=".\@=\|$" containedin=cCppInIf contains=cCppInElse2 fold
#   syn region	cCppInElse	contained start="^\s*\%(%:\|#\)\s*\%(else\>\|elif\s\+\%(0*[1-9]\d*\s*\%($\|//\|/\*\||\)\)\@!\)" end=".\@=\|$" containedin=cCppInIf contains=cCppInElse2
#   syn region	cCppInElse2	contained matchgroup=cCppInWrapper start="^\s*\%(%:\|#\)\s*\%(else\|elif\)\%([^/]\|/[^/*]\)*" end="^\s*\%(%:\|#\)\s*endif\>"me=s-1 contains=cSpaceError,cCppOutSkip,@Spell
#   syn region	cCppOutSkip	contained start="^\s*\%(%:\|#\)\s*\%(if\>\|ifdef\>\|ifndef\>\)" skip="\\$" end="^\s*\%(%:\|#\)\s*endif\>" contains=cSpaceError,cCppOutSkip
#   syn region	cCppInSkip	contained matchgroup=cCppInWrapper start="^\s*\%(%:\|#\)\s*\%(if\s\+\%(\d\+\s*\%($\|//\|/\*\||\|&\)\)\@!\|ifdef\>\|ifndef\>\)" skip="\\$" end="^\s*\%(%:\|#\)\s*endif\>" containedin=cCppOutElse,cCppInIf,cCppInSkip contains=TOP,cPreProc
#   syn region	cIncluded	display contained start=+"+ skip=+\\\\\|\\"+ end=+"+
#   syn match	cIncluded	display contained "<[^>]*>"
#   syn match	cInclude	display "^\s*\zs\%(%:\|#\)\s*include\>\s*["<]" contains=cIncluded
#   syn cluster	cPreProcGroup	contains=cPreCondit,cIncluded,cInclude,cDefine,cErrInParen,cErrInBracket,cUserLabel,cSpecial,cOctalZero,cCppOutWrapper,cCppInWrapper,@cCppOutInGroup,cFormat,cNumber,cFloat,cOctal,cOctalError,cNumbersCom,cString,cCommentSkip,cCommentString,cComment2String,@cCommentGroup,cCommentStartError,cParen,cBracket,cMulti,cBadBlock
#   syn region	cDefine		start="^\s*\zs\%(%:\|#\)\s*\%(define\|undef\)\>" skip="\\$" end="$" keepend contains=ALLBUT,@cPreProcGroup,@Spell
#   syn region	cPreProc	start="^\s*\zs\%(%:\|#\)\s*\%(pragma\>\|line\>\|warning\>\|warn\>\|error\>\)" skip="\\$" end="$" keepend contains=ALLBUT,@cPreProcGroup,@Spell
#   syn match cAutodocReal display contained "\%(//\|[/ \t\v]\*\|^\*\)\@2<=!.*" contains=@cAutodoc containedin=cComment,cCommentL
#   syn cluster cCommentGroup add=cAutodocReal
#   syn cluster cPreProcGroup add=cAutodocReal
#   syn region	cPragma		start="^\s*#pragma\s\+region\>" end="^\s*#pragma\s\+endregion\>" transparent keepend extend fold
#   syn cluster	cMultiGroup	contains=cIncluded,cSpecial,cCommentSkip,cCommentString,cComment2String,@cCommentGroup,cCommentStartError,cUserCont,cUserLabel,cBitField,cOctalZero,cCppOutWrapper,cCppInWrapper,@cCppOutInGroup,cFormat,cNumber,cFloat,cOctal,cOctalError,cNumbersCom,cCppParen,cCppBracket,cCppString
#   syn region	cMulti		transparent start='?' skip='::' end=':' contains=ALLBUT,@cMultiGroup,@Spell,@cStringGroup
#   syn cluster	cLabelGroup	contains=cUserLabel
#   syn match	cUserCont	display "^\s*\zs\I\i*\s*:$" contains=@cLabelGroup
#   syn match	cUserCont	display ";\s*\zs\I\i*\s*:$" contains=@cLabelGroup
#   syn match	cUserCont	display "^\s*\zs\%(class\|struct\|enum\)\@!\I\i*\s*:[^:]"me=e-1 contains=@cLabelGroup
#   syn match	cUserCont	display ";\s*\zs\%(class\|struct\|enum\)\@!\I\i*\s*:[^:]"me=e-1 contains=@cLabelGroup
#   syn match	cUserCont	display "^\s*\zs\I\i*\s*:[^:]"me=e-1 contains=@cLabelGroup
#   syn match	cUserCont	display ";\s*\zs\I\i*\s*:[^:]"me=e-1 contains=@cLabelGroup
#   syn match	cUserLabel	display "\I\i*" contained
#   syn match	cBitField	display "^\s*\zs\I\i*\s*:\s*[1-9]"me=e-1 contains=cType
#   syn match	cBitField	display ";\s*\zs\I\i*\s*:\s*[1-9]"me=e-1 contains=cType
#   syn sync fromstart
#   exec "syn sync ccomment cComment minlines=" . b:c_minlines
}

keywords = ''

for kw in keywords.split():
    if kw in hl_map:
        hl_map[kw] = 'Keyword'

log = functools.partial(vpe.call_soon, print)


class CCodeHandler(Handler):
    pass


root_handler_type = CCodeHandler
lang_name = 'c'
source_name = 'c'
