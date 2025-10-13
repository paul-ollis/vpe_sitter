==========
Change Log
==========

Version 0.2.0
-------------

- Implemented a work around that seems to solve the change buffering associated
  with Vim listener_add mechanism.

- Added support for user configuration of languages.

- Added extra commands to help users add supported languages.


Version 0.1.2
-------------

Just bumped VPE version requirement to 0.7.1.


Version 0.1.1
-------------

- Work around for possible Vim timer bug on Windows, #1. This was preventing
  correct operation on Windows for large files.

- Added command ``Treesit debug all on|off``.
