---
name: Bug report
about: Report something that does not work as expected
title: ''
labels: ''
assignees: ''
---

Describe the bug
----------------

A clear and concise description of what goes wrong.

To Reproduce
------------

Steps to reproduce the behaviour:
1.  Open '...'
2.  Click on '....'
3.  See error

Expected behaviour
------------------

What you expected to happen instead.

Which view
----------

Does it happen while **arranging** (the thumbnail grid), while **reading**
(View ▸ Read Mode), or both?

Input files
-----------

Does it happen with every document, or only some? If it is specific to one
file, please attach it, or a few pages of it, if you are able to share it.

Screenshots
-----------

If it is visual, a screenshot usually explains it faster than words.

Console output
--------------

If you can run it from a terminal, please include anything it printed:

    python -m pdfarranger_qt

Qt writes warnings there that never reach the window, and they are often the
quickest route to the cause.

Version
-------

-   **The full version from Help ▸ About** — it looks like `0.1.0 (1349)`, and
    the number in brackets is the git commit the build came from. Please give
    the whole thing; the release installers can be well behind `main`, and that
    number is what says which code you are actually running.
-   How you installed it: the Windows installer, or run from source
-   OS name and version, e.g. Windows 11, Fedora 42, macOS 15
-   If running from source: the output of `pip list` for PySide6 and pikepdf
