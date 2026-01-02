"""Controllers for setting time_slot values."""

from .ghostblock_controller import apply_ghostblock_controller
from .slot_oracle_controller import apply_slot_oracle_controller

__all__ = ['apply_ghostblock_controller', 'apply_slot_oracle_controller']
