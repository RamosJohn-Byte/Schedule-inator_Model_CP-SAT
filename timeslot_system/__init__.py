"""
Timeslot System Module

This module provides a flexible abstraction layer for managing time slot occupancy
in scheduling problems. It separates the core time slot grid from the mechanisms
that control how time slots get their values.

Architecture:
    - timeslot_grid.py: Pure time_slot boolean variable creation
    - streak_tracker.py: Streak analysis (active/vacant consecutive slots)
    - timeslot_constraints.py: Logical constraints (max class, min gap, etc.)
    - controllers/: Pluggable mechanisms to set time_slot values
        - ghostblock_controller.py: Ghost interval-based vacancy tracking
        - (future: direct_interval_controller.py, hybrid_controller.py, etc.)
    - debug/: Visualization and debugging utilities
"""

__version__ = "1.0.0"
