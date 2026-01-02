"""
Time Slot Grid - Core Interface Layer

This module creates the core time_slot boolean variable arrays that serve as
the abstraction layer for all scheduling constraints. Time slots represent
whether a particular time period is OCCUPIED (1) or VACANT (0).

The actual mechanism for setting these values is delegated to controller modules
(e.g., ghostblock_controller.py), allowing for flexible experimentation with
different constraint modeling approaches.
"""

def create_timeslot_grid_data(model, faculty, batches, config):
    """
    Create storage dictionaries for time slot data without creating the actual
    time_slot variables (those are created by controllers).
    
    This function just initializes the data structure that controllers will populate.
    
    Args:
        model: CP-SAT model instance
        faculty: List of Faculty objects
        batches: List of Batch objects
        config: Configuration dictionary
        
    Returns:
        Dictionary containing:
            - 'faculty_data': {} - to be populated by controller
            - 'batch_data': {} - to be populated by controller
            - 'config': config - reference for controllers
            - 'constants': {} - useful constants
    """
    
    MINUTES_IN_A_DAY = 1440
    FRIDAY_IDX = 4
    TIME_GRANULARITY = config.get("TIME_GRANULARITY_MINUTES", 10)
    
    # Helper function to calculate slots per day
    def calculate_slots_for_day(day_idx, config):
        """Calculate number of TIME_GRANULARITY slots for a given day"""
        day_start = config["DAY_START_MINUTES"]
        day_end = config["FRIDAY_END_MINUTES"] if day_idx == FRIDAY_IDX else config["DAY_END_MINUTES"]
        day_span = day_end - day_start
        return day_span // TIME_GRANULARITY
    
    timeslot_data = {
        'faculty_data': {},  # Will be populated as (f_idx, day_idx) -> list of slot dicts
        'batch_data': {},    # Will be populated as (b_idx, day_idx) -> list of slot dicts
        'config': config,
        'constants': {
            'MINUTES_IN_A_DAY': MINUTES_IN_A_DAY,
            'FRIDAY_IDX': FRIDAY_IDX,
            'TIME_GRANULARITY': TIME_GRANULARITY,
            'calculate_slots_for_day': calculate_slots_for_day
        }
    }
    
    return timeslot_data
