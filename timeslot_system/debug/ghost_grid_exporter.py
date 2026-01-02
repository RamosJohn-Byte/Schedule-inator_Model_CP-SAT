"""
Ghost Grid Debug Exporter

Exports ghost block activation grids showing which time slots are vacant vs occupied,
along with streak analysis data.
"""

import os
from datetime import datetime


def print_ghost_grid_debug(faculty_ghost_grid, batch_ghost_grid, faculty, batches, config, solver,
                          faculty_active_streak, faculty_vacant_streak,
                          batch_active_streak, batch_vacant_streak,
                          faculty_block_ends, batch_block_ends,
                          faculty_gap_ends_here, batch_gap_ends_here,
                          output_dir=None, pass_name=""):
    """
    Print Ghost Block activation grid showing which time slots are vacant (X) vs occupied (O).
    
    Format (Time slots per ROW):
        Time Range       | Status | ActiveStreak | VacantStreak | State
        8:00 AM - 8:30 AM | O      | 1            | 0            | OCCUPIED
        8:30 AM - 9:00 AM | X      | 0            | 1            | VACANT
    
    X = Ghost Active (Vacancy exists)
    O = Ghost Inactive (Occupied by class)
    ActiveStreak = Consecutive CLASS slots ending at this position
    VacantStreak = Consecutive GAP slots ending at this position
    """
    
    def minutes_to_12hr_time(minutes):
        """Convert absolute minutes to 12-hour format (e.g., 8:00 AM)"""
        MINUTES_IN_A_DAY = 1440
        day_minutes = minutes % MINUTES_IN_A_DAY
        hours = day_minutes // 60
        mins = day_minutes % 60
        
        period = "AM" if hours < 12 else "PM"
        display_hour = hours if hours <= 12 else hours - 12
        if display_hour == 0:
            display_hour = 12
        
        return f"{display_hour}:{mins:02d} {period}"
    
    filename = f"ghost_grid_{pass_name}.txt" if pass_name else "ghost_grid.txt"
    if output_dir:
        filepath = os.path.join(output_dir, filename)
    else:
        filepath = filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("=" * 120 + "\n")
        f.write(f"GHOST BLOCK ACTIVATION GRID - {pass_name.upper()}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 120 + "\n\n")
        
        f.write("LEGEND:\n")
        f.write("  X = Ghost Active (Vacancy exists - time slot is EMPTY)\n")
        f.write("  O = Ghost Inactive (Occupied - time slot has CLASS)\n")
        f.write("  ActiveStreak = Consecutive CLASS slots ending at this position\n")
        f.write("  VacantStreak = Consecutive GAP slots ending at this position\n")
        f.write("  BlockEnds = 1 if this slot ends a class block, 0 otherwise\n")
        f.write("  GapEnds = 1 if this slot ends a gap (followed by class), 0 otherwise, N/A for last slot\n")
        f.write("-" * 120 + "\n\n")
        
        # Faculty Ghost Grids
        f.write("\n" + "=" * 120 + "\n")
        f.write("FACULTY GHOST GRIDS\n")
        f.write("=" * 120 + "\n\n")
        
        for f_idx, fac in enumerate(faculty):
            f.write(f"\n{'─' * 120}\n")
            f.write(f"Faculty {f_idx}: {fac.name}\n")
            f.write(f"{'─' * 120}\n\n")
            
            for day_idx in range(len(config["SCHEDULING_DAYS"])):
                day_name = config["SCHEDULING_DAYS"][day_idx]
                f.write(f"{day_name} (Day {day_idx}):\n")
                f.write(f"{'Time Range':<25} | {'Status':<6} | {'ActiveStreak':<12} | {'VacantStreak':<12} | {'BlockEnds':<10} | {'GapEnds':<8} | {'State'}\n")
                f.write(f"{'-'*25} | {'-'*6} | {'-'*12} | {'-'*12} | {'-'*10} | {'-'*8} | {'-'*40}\n")
                
                ghost_slots = faculty_ghost_grid[(f_idx, day_idx)]
                active_streaks = faculty_active_streak.get((f_idx, day_idx), [])
                vacant_streaks = faculty_vacant_streak.get((f_idx, day_idx), [])
                block_ends_list = faculty_block_ends.get((f_idx, day_idx), [])
                gap_ends_list = faculty_gap_ends_here.get((f_idx, day_idx), [])
                
                for slot_idx, ghost_slot in enumerate(ghost_slots):
                    start_abs = ghost_slot["start_abs"]
                    end_abs = ghost_slot["end_abs"]
                    
                    # Handle both controller types (ghost_active for ghost blocks, time_slot for slot oracle)
                    try:
                        if "ghost_active" in ghost_slot:
                            # Ghost Block Controller: time_slot = NOT(ghost_active)
                            ghost_active = ghost_slot["ghost_active"]
                            is_ghost_active = solver.Value(ghost_active)
                            status = "X" if is_ghost_active else "O"
                            state = "VACANT" if is_ghost_active else "OCCUPIED"
                        else:
                            # Slot Oracle Controller: time_slot directly indicates occupation
                            time_slot = ghost_slot["time_slot"]
                            is_occupied = solver.Value(time_slot)
                            status = "O" if is_occupied else "X"
                            state = "OCCUPIED" if is_occupied else "VACANT"
                    except:
                        status = "?"
                        state = "UNKNOWN"
                    
                    # Get streak values
                    try:
                        active_val = solver.Value(active_streaks[slot_idx]) if slot_idx < len(active_streaks) else "?"
                        vacant_val = solver.Value(vacant_streaks[slot_idx]) if slot_idx < len(vacant_streaks) else "?"
                        
                        # Get block_ends and gap_ends values (always 0 or 1)
                        block_ends_val = solver.Value(block_ends_list[slot_idx]) if slot_idx < len(block_ends_list) else 0
                        gap_ends_val = solver.Value(gap_ends_list[slot_idx]) if slot_idx < len(gap_ends_list) and gap_ends_list[slot_idx] is not None else 0
                    except:
                        active_val = "?"
                        vacant_val = "?"
                        block_ends_val = 0
                        gap_ends_val = 0
                    
                    time_range = f"{minutes_to_12hr_time(start_abs)} - {minutes_to_12hr_time(end_abs)}"
                    f.write(f"{time_range:<25} | {status:<6} | {str(active_val):<12} | {str(vacant_val):<12} | {str(block_ends_val):<10} | {str(gap_ends_val):<8} | {state}\n")
                
                f.write("\n")
        
        # Batch Ghost Grids
        f.write("\n\n" + "=" * 120 + "\n")
        f.write("BATCH GHOST GRIDS\n")
        f.write("=" * 120 + "\n\n")
        
        for b_idx, batch in enumerate(batches):
            f.write(f"\n{'─' * 120}\n")
            f.write(f"Batch {b_idx}: {batch.batch_id}\n")
            f.write(f"{'─' * 120}\n\n")
            
            for day_idx in range(len(config["SCHEDULING_DAYS"])):
                day_name = config["SCHEDULING_DAYS"][day_idx]
                f.write(f"{day_name} (Day {day_idx}):\n")
                f.write(f"{'Time Range':<25} | {'Status':<6} | {'ActiveStreak':<12} | {'VacantStreak':<12} | {'BlockEnds':<10} | {'GapEnds':<8} | {'State'}\n")
                f.write(f"{'-'*25} | {'-'*6} | {'-'*12} | {'-'*12} | {'-'*10} | {'-'*8} | {'-'*40}\n")
                
                ghost_slots = batch_ghost_grid[(b_idx, day_idx)]
                active_streaks = batch_active_streak.get((b_idx, day_idx), [])
                vacant_streaks = batch_vacant_streak.get((b_idx, day_idx), [])
                block_ends_list = batch_block_ends.get((b_idx, day_idx), [])
                gap_ends_list = batch_gap_ends_here.get((b_idx, day_idx), [])
                
                for slot_idx, ghost_slot in enumerate(ghost_slots):
                    start_abs = ghost_slot["start_abs"]
                    end_abs = ghost_slot["end_abs"]
                    
                    # Handle both controller types (ghost_active for ghost blocks, time_slot for slot oracle)
                    try:
                        if "ghost_active" in ghost_slot:
                            # Ghost Block Controller: time_slot = NOT(ghost_active)
                            ghost_active = ghost_slot["ghost_active"]
                            is_ghost_active = solver.Value(ghost_active)
                            status = "X" if is_ghost_active else "O"
                            state = "VACANT" if is_ghost_active else "OCCUPIED"
                        else:
                            # Slot Oracle Controller: time_slot directly indicates occupation
                            time_slot = ghost_slot["time_slot"]
                            is_occupied = solver.Value(time_slot)
                            status = "O" if is_occupied else "X"
                            state = "OCCUPIED" if is_occupied else "VACANT"
                    except:
                        status = "?"
                        state = "UNKNOWN"
                    
                    # Get streak values
                    try:
                        active_val = solver.Value(active_streaks[slot_idx]) if slot_idx < len(active_streaks) else "?"
                        vacant_val = solver.Value(vacant_streaks[slot_idx]) if slot_idx < len(vacant_streaks) else "?"
                        
                        # Get block_ends and gap_ends values (always 0 or 1)
                        block_ends_val = solver.Value(block_ends_list[slot_idx]) if slot_idx < len(block_ends_list) else 0
                        gap_ends_val = solver.Value(gap_ends_list[slot_idx]) if slot_idx < len(gap_ends_list) and gap_ends_list[slot_idx] is not None else 0
                    except:
                        active_val = "?"
                        vacant_val = "?"
                        block_ends_val = 0
                        gap_ends_val = 0
                    
                    time_range = f"{minutes_to_12hr_time(start_abs)} - {minutes_to_12hr_time(end_abs)}"
                    f.write(f"{time_range:<25} | {status:<6} | {str(active_val):<12} | {str(vacant_val):<12} | {str(block_ends_val):<10} | {str(gap_ends_val):<8} | {state}\n")
                
                f.write("\n")
        
        f.write("\n" + "=" * 120 + "\n")
    
    print(f"[Ghost Grid Debug] {pass_name} exported to: {filepath}")
