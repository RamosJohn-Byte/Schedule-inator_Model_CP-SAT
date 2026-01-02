"""
Ghost Block System - Exclusive Components

This package contains components that are ONLY used with the Ghost Block Controller.
These should NOT be used with other controllers like Slot Oracle.
"""

from .ghost_grid_exporter import export_ghostblock_debug

__all__ = ['export_ghostblock_debug']
