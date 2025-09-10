::

     _    ______  ______    _____ _ __  __
    | |  / / __ \/ ____/   / ___/(_) /_/ /____  _____
    | | / / /_/ / __/      \__ \/ / __/ __/ _ \/ ___/
    | |/ / ____/ /___     ___/ / / /_/ /_/  __/ /     Tree-sitter in Vim
    |___/_/   /_____/____/____/_/\__/\__/\___/_/

Welcome to the Tree-sitter support for Vim.

:status:
    This is version 0.1.0

    This is alpha software, but I use it all the time for syntax highlighting
    and it has been behaving reliably for me.

    This library is targeted at 'vanilla' `Vim`_. It is doubtful that this could
    easily be made to work with Neovim and, in any case, Neovim already has
    fairly mature `support for Tree-sitter`_.


Introduction
============

This library is a plugin for `VPE`_.

`Tree-sitter`_ is an incremental parsing library that is intended to be fast
enough to be integrated into text editors in order to provide syntax aware
tooling. One obvious use is as a mechanism to implement syntax highlighting,
which is the primary reason that this library exist; *i.e.* to support
`VPE_Syntax`_.

This library provides a mechanism to associate a Tree-sitter parse tree with any
buffer that displays a supported language. Client code of this library can
register to receive callbacks whenever the tree has been updated.

The following example demonstrate the main parts of the API. First tree-sitter
must be enabled for a buffer.

.. code:: python

    import vpe
    import vpe_sitter
    from vpe import vim
    from vpe_sitter.listen import Listener, ConditionCode, AffectedLines

    # Try enabling tree-sitter for the current buffer.
    if msg := vpe_sitter.treesit_current_buffer():
        # Not possible for this buffer. Most likely because the buffer's
        # filetype is not a supported language.
        vpe.error_msg(msg)
    else:
        buf: vpe.Buffer = vim.current.buffer
        listener: Listener = buf.store('tree-sitter').listener

Multiple clients can do this, they will all share the same Tree-sitter
``Listener`` instance. The client will need to provide a callback function
along the lines of:

.. code:: python

    def handle_tree_change(
            code: ConditionCode, affected_lines: AffectedLines) -> None:
        """Handle a tree change notification.

        The affected_lines parameter is a list of Python ranges.
        """
        match code:
            case ConditionCode.NEW_CLEAN_TREE:
                # A new tree that matches the buffer is available.

            case ConditionCode.NEW_OUT_OF_DATE_TREE:
                # A new tree is available, but the buffer changed during
                # parsing.

            case ConditionCode.PENDING_CHANGES:
                # Changes to the buffer have been detected and a new parse tree
                # will be generated shortly.

You can then register for callbacks using the ``Listener`` instance.

.. code:: python

    listener.add_parse_complete_callback(handle_tree_change)

Client code will typically have to use the generated Tree-sitter ``Tree``
instance, which is available as the ``Listener.tree`` property. See
`the Tree-sitter Tree`_ documentation for the API available to client code.
Be warned that this link points to the documentation for the latest Tree-sitter
Python bindings, not the ones use by this library. Watch this space for online
documentation that will define a version correct API for `Tree` object.


.. _Tree-sitter: https://tree-sitter.github.io/tree-sitter/
.. _Vim: https://www.vim.org/
.. _support for Tree-sitter: https://neovim.io/doc/user/treesitter.html
.. _vpe: https://github.com/paul-ollis/vim-vpe
.. _vpe_syntax: https://github.com/paul-ollis/vpe_syntax
.. _the Tree-sitter Tree:
    https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.Tree.html
