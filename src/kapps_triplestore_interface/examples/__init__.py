"""Runnable examples for the triplestore interface.

The files in this directory are the payload of the ``kapps-triplestore-examples`` console
command. It copies them out of the installed package into a directory that you own, because a
file inside ``site-packages`` is not one you can open, edit or re-run. The scripts import their
connection helper flatly (``from _store import ...``), so they run from whatever directory they
are copied into, not from here.
"""
