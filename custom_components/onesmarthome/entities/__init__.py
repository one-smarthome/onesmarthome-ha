"""Home Assistant entity classes for every Grenton widget.

Each module here defines the concrete entity for one HA platform. They all sit
on :class:`~.base.GrentonEntity`, which binds them to the shared
:class:`~..runtime.hub.GrentonHub` so a single push report re-renders every
entity that reads the changed slot.
"""
