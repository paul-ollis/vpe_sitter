"""Python specific Tree-sitter support."""

import keyword
import functools
from typing import Dict, Tuple

import vpe

from vpe_sitter.listen import Handler

log = functools.partial(vpe.call_soon, print)


class NamedConstructHandler(Handler):
    """Mix-in for handler of constructs that a are given a name.

    This handles classes, functions and methods.
    """
    sm_spec = (
        ('IDLE',          'def',        'name_expected', None),
        ('IDLE',          'class',      'name_expected', None),
        ('name_expected', 'identifier', 'named',         'add_ident'),
    )

    def add_ident(self):
        """Add an identifier to the ident_path."""
        self.root.ident_path.append(self.extract_code(self.buf, self.node))

    def leave(self):
        """Leave a level in the parse tree."""
        path = self.root.ident_path
        if path:
            path.pop()


class ClassHandler(NamedConstructHandler):
    type_conversion_table = {
        ('name_expected', 'identifier'): 'class_name',
    }
    handler_switch_table = {
        ('*', 'block'): 'ClassBlockHandler',
    }

class FunctionHandlerCommon(NamedConstructHandler):
    type_conversion_table = {
        ('name_expected', 'identifier'): 'func_name',
    }
    handler_switch_table = {
        ('*', 'block'):      'FunctionBlockHandler',
        ('*', 'parameters'): 'ParamsHandler',
    }


class FunctionHandler(FunctionHandlerCommon): pass


class MethodHandler(FunctionHandlerCommon):
    alt_lookup_table = {
        'identifier': {'self': 'self_identifier'},
    }
    ndhandler_switch_table = {
        ('*', 'block'):      'MethodBlockHandler',
        ('*', 'parameters'): 'MethodParamsHandler',
    }


class ClassMethodHandler(FunctionHandlerCommon):
    alt_lookup_table = {
        'identifier': {'cls': 'cls_identifier'},
    }
    handler_switch_table = {
        ('*', 'block'):      'ClassMethodBlockHandler',
        ('*', 'parameters'): 'ClassMethodParamsHandler',
    }


class StaticMethodHandler(FunctionHandlerCommon):
    handler_switch_table = {
        ('*', 'block'):      'StaticMethodBlockHandler',
        ('*', 'parameters'): 'StaticMethodParamsHandler',
    }


class BlockHandler(Handler):
    """The block or body within a module, class, statement, *etc*."""
    handler_switch_table: Dict[Tuple[str, str], str] = {
        ('*', 'function_definition'):  'FunctionHandler',
        ('*', 'class_definition'):     'ClassHandler',
        ('*', 'if_statement'):         'StatementHandler',
        ('*', 'while_statement'):      'StatementHandler',
        ('*', 'expression_statement'): 'StatementHandler',
        ('*', 'with_statement'):       'StatementHandler',
        ('*', 'for_statement'):        'StatementHandler',
        ('*', 'decorated_definition'): 'DecoratedDefinitionHandler',
    }


class DocstringedBlockHandler(BlockHandler):
    """The block that can have a docstring."""
    sm_spec = (
        ('IDLE',     'expression_statement', 'poss_doc', None),
        ('poss_doc', '*',                    'END',      None),
        ('IDLE',     '*',                    'END',      None),
    )
    handler_switch_table: Dict[Tuple[str, str], str] = {
        ('poss_doc', 'expression_statement'): 'DocstringStatementHandler',
    }


class StatementHandler(Handler):
    handler_switch_table = {
        ('*', 'block'):                'BlockHandler',
    }


class DocstringStatementHandler(StatementHandler):
    type_conversion_table = {
        ('IDLE', 'string'): 'doc_string',
    }
    sm_spec = (
        ('IDLE', '*',  'END', None),
    )


class ModuleBlockHandler(DocstringedBlockHandler): pass
class FunctionBlockHandler(DocstringedBlockHandler): pass
class MethodBlockHandler(DocstringedBlockHandler): pass
class ClassMethodBlockHandler(DocstringedBlockHandler): pass
class StaticMethodBlockHandler(DocstringedBlockHandler): pass


class ClassBlockHandler(DocstringedBlockHandler):
    handler_switch_table = {
        ('*', 'function_definition'):  'MethodHandler',
    }


class ParamsHandler(Handler):
    type_conversion_table = {
        ('*', 'identifier'): 'plain_parameter',
    }


class DecoratedDefinitionHandler(BlockHandler):
    event_lookup_table = (
        ('identifier', 'identifier', 'extract_code'),
    )
    sm_spec = (
        ('IDLE',       'decorator',    'decorator',    None),
        ('decorator',  '@',            'identifier',   None),
        ('identifier', 'classmethod',  'classmethod',  None),
        ('identifier', 'staticmethod', 'staticmethod',  None),
    )
    handler_switch_table = {
        ('classmethod', 'function_definition'):  'ClassMethodHandler',
        ('staticmethod', 'function_definition'):  'StaticMethodHandler',
    }


class MethodParamsHandler(Handler):
    event_lookup_table = (
        ('self_expected', 'identifier', 'extract_code'),
    )
    type_conversion_table = {
        ('self_expected', 'self'): 'self_parameter',
        ('self_expected', '*'): 'bad_self_parameter',
    }
    sm_spec = (
        ('IDLE',          '(',          'self_expected', None),
        ('self_expected', '*',          'END',           None),
    )


class ClassMethodParamsHandler(MethodParamsHandler):
    type_conversion_table = {
        ('self_expected', 'cls'): 'cls_parameter',
        ('self_expected', '*'): 'bad_cls_parameter',
    }


class StaticMethodParamsHandler(MethodParamsHandler):
    type_conversion_table = {
        ('self_expected', 'cls'): 'dodgy_cls_parameter',
        ('self_expected', 'self'): 'dodgy_self_parameter',
    }


hl_map = {
    'async': 'Keyword',
    'await': 'Keyword',
    'class': 'Class',
    'class_name': 'ClassName',
    'comment': 'Comment',
    'def': 'Keyword',
    'doc_string': 'DocString',
    'false': 'StandardConst',
    'float': 'FloatNumber',
    'func_name': 'FunctionName',
    'method_name': 'MethodName',
    'identifier': 'Identifier',
    'integer': 'Number',
    'none': 'StandardConst',
    'pass_statement': 'Pass',
    'string': 'String',
    'true': 'StandardConst',
    'self_parameter': 'Self',
    'self_identifier': 'Self',
    'cls_parameter': 'Cls',
    'cls_identifier': 'Cls',
    'bad_self_parameter': 'NonStandardSelf',
    'dodgy_self_parameter': 'NonStandardSelf',
    'bad_cls_parameter': 'NonStandardCls',
    'dodgy_cls_parameter': 'NonStandardCls',
    'staticmethod': 'StaticMethodDecorator',
    'classmethod': 'ClassMethodDecorator',
}

for name in keyword.kwlist:
    hl_map[name] = 'Keyword'

root_handler_type = ModuleBlockHandler
lang_name = source_name = 'python'
