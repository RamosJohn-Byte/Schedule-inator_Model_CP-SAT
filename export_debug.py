# export_debug.py
"""
Debug and diagnostic export functions for solver analysis.
Includes solver diagnostics, ghost grid visualization, and meeting debug exports.
"""

import os
from datetime import datetime
from ortools.sat.python import cp_model


# ============================================================================
# SOLVER DIAGNOSTICS CONFIGURATION
# ============================================================================
ENABLE_SOLVER_DIAGNOSTICS = False  # Set to False to disable diagnostic output

# Global variable to store diagnostics file path (set by run_scheduler)
_diagnostics_file_path = None


def write_solver_diagnostics(solver, model, status, pass_name="", output_dir=None):
    """
    Write comprehensive solver diagnostics to a file for later review.
    Shows search statistics, efficiency metrics, and interpretation.
    
    Args:
        solver: CpSolver instance after solving
        model: CpModel instance
        status: Solve status code
        pass_name: Name of the pass (e.g., "PASS 1", "PASS 2")
        output_dir: Directory to write diagnostics file (uses global if None)
    """
    if not ENABLE_SOLVER_DIAGNOSTICS:
        return
    
    global _diagnostics_file_path
    
    # Determine output file path
    if output_dir:
        diagnostics_path = os.path.join(output_dir, "solver_diagnostics.txt")
        _diagnostics_file_path = diagnostics_path
    elif _diagnostics_file_path:
        diagnostics_path = _diagnostics_file_path
    else:
        diagnostics_path = "solver_diagnostics.txt"
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(diagnostics_path) if os.path.dirname(diagnostics_path) else ".", exist_ok=True)
    
    # Build the diagnostics report as a list of lines
    lines = []
    
    lines.append("")
    lines.append("=" * 100)
    lines.append(f"SOLVER DIAGNOSTICS - {pass_name}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 100)
    
    # ==================== BASIC STATISTICS ====================
    lines.append("")
    lines.append("BASIC STATISTICS:")
    lines.append(f"   Status:              {solver.StatusName(status)}")
    lines.append(f"   Wall time:           {solver.WallTime():.2f} seconds")
    lines.append(f"   User time:           {solver.UserTime():.2f} seconds")
    
    # ==================== SEARCH STATISTICS ====================
    lines.append("")
    lines.append("SEARCH STATISTICS:")
    lines.append(f"   Branches:            {solver.NumBranches():,}")
    lines.append(f"   Conflicts:           {solver.NumConflicts():,}")
    
    # ==================== OBJECTIVE INFORMATION ====================
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        obj_value = solver.ObjectiveValue()
        best_bound = solver.BestObjectiveBound()
        gap = abs(obj_value - best_bound)
        gap_percent = (gap / max(abs(obj_value), 1)) * 100 if obj_value != 0 else 0
        
        lines.append("")
        lines.append("OBJECTIVE:")
        lines.append(f"   Current value:       {obj_value:,}")
        lines.append(f"   Best bound:          {best_bound:,}")
        lines.append(f"   Gap:                 {gap:,} ({gap_percent:.2f}%)")
        
        if status == cp_model.OPTIMAL:
            lines.append(f"   [OPTIMAL] - Proven best solution!")
        else:
            lines.append(f"   [FEASIBLE] - Not proven optimal")
            lines.append(f"   Need to close gap of {gap:,} to prove optimality")
    
    # ==================== MODEL SIZE ====================
    lines.append("")
    lines.append("MODEL SIZE:")
    proto = model.Proto()
    lines.append(f"   Variables:           {len(proto.variables):,}")
    lines.append(f"   Constraints:         {len(proto.constraints):,}")
    
    # Count constraint types
    constraint_types = {}
    for c in proto.constraints:
        c_type = c.WhichOneof('constraint')
        constraint_types[c_type] = constraint_types.get(c_type, 0) + 1
    
    lines.append("")
    lines.append("   Constraint breakdown:")
    for c_type, count in sorted(constraint_types.items(), key=lambda x: -x[1])[:15]:
        lines.append(f"      {c_type}: {count:,}")
    
    # ==================== EFFICIENCY METRICS ====================
    if solver.WallTime() > 0:
        branches_per_sec = solver.NumBranches() / solver.WallTime()
        conflicts_per_sec = solver.NumConflicts() / solver.WallTime()
        
        lines.append("")
        lines.append("EFFICIENCY METRICS:")
        lines.append(f"   Branches/second:     {branches_per_sec:,.0f}")
        lines.append(f"   Conflicts/second:    {conflicts_per_sec:,.0f}")
        
        # Conflict ratio
        if solver.NumBranches() > 0:
            conflict_ratio = solver.NumConflicts() / solver.NumBranches() * 100
            lines.append(f"   Conflict ratio:      {conflict_ratio:.2f}%")
    
    # ==================== INTERPRETATION ====================
    lines.append("")
    lines.append("INTERPRETATION:")
    
    if solver.WallTime() > 0:
        conflicts_per_sec = solver.NumConflicts() / solver.WallTime()
        branches_per_sec = solver.NumBranches() / solver.WallTime()
        
        # Conflict rate interpretation
        if conflicts_per_sec < 100:
            lines.append(f"   [WARNING] Very low conflict rate ({conflicts_per_sec:.0f}/s) - solver may be stuck")
            lines.append(f"       Possible causes: complex propagation, weak bounds")
        elif conflicts_per_sec < 1000:
            lines.append(f"   [INFO] Low conflict rate ({conflicts_per_sec:.0f}/s) - heavy propagation per conflict")
        elif conflicts_per_sec > 50000:
            lines.append(f"   [WARNING] Very high conflict rate ({conflicts_per_sec:.0f}/s) - may be thrashing")
            lines.append(f"       Possible causes: tightly coupled constraints, poor search heuristics")
        else:
            lines.append(f"   [OK] Normal conflict rate ({conflicts_per_sec:.0f}/s)")
        
        # Branch rate interpretation
        if branches_per_sec < 1000:
            lines.append(f"   [WARNING] Low branch rate ({branches_per_sec:.0f}/s) - slow constraint evaluation")
        elif branches_per_sec > 100000:
            lines.append(f"   [OK] High branch rate ({branches_per_sec:.0f}/s) - efficient search")
        else:
            lines.append(f"   [OK] Moderate branch rate ({branches_per_sec:.0f}/s)")
    
    # Status-specific interpretation
    if status == cp_model.FEASIBLE:
        lines.append("")
        lines.append("WHY NOT OPTIMAL?")
        lines.append("   The solver found a solution but couldn't prove it's the best.")
        lines.append("   Possible reasons:")
        lines.append("   1. Time limit reached before proof completed")
        lines.append("   2. Model has too many variables/constraints for quick proof")
        lines.append("   3. Objective function has many near-optimal solutions")
        lines.append("   4. Large gap between current solution and lower bound")
        if solver.WallTime() > 0:
            gap = abs(solver.ObjectiveValue() - solver.BestObjectiveBound())
            if gap > 0:
                time_per_gap = solver.WallTime() / max(1, gap)
                lines.append(f"")
                lines.append(f"   Estimated time to close gap: ~{gap * time_per_gap / 60:.1f} more minutes")
    
    lines.append("=" * 100)
    lines.append("")
    
    # Write to file (append mode to capture both passes)
    with open(diagnostics_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    # Also print a brief summary to terminal
    print(f"\n[Diagnostics] {pass_name}: {solver.StatusName(status)} in {solver.WallTime():.2f}s")
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        gap = abs(solver.ObjectiveValue() - solver.BestObjectiveBound())
        print(f"[Diagnostics] Objective: {solver.ObjectiveValue():,} | Gap: {gap:,} | Branches: {solver.NumBranches():,}")
    print(f"[Diagnostics] Full report saved to: {diagnostics_path}")


def print_ghost_grid_debug(faculty_ghost_grid, batch_ghost_grid, faculty, batches, config, solver,
                          faculty_active_streak, faculty_vacant_streak,
                          batch_active_streak, batch_vacant_streak,
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
                f.write(f"{'Time Range':<25} | {'Status':<6} | {'ActiveStreak':<12} | {'VacantStreak':<12} | {'State'}\n")
                f.write(f"{'-'*25} | {'-'*6} | {'-'*12} | {'-'*12} | {'-'*40}\n")
                
                ghost_slots = faculty_ghost_grid[(f_idx, day_idx)]
                active_streaks = faculty_active_streak.get((f_idx, day_idx), [])
                vacant_streaks = faculty_vacant_streak.get((f_idx, day_idx), [])
                
                for slot_idx, ghost_slot in enumerate(ghost_slots):
                    start_abs = ghost_slot["start_abs"]
                    end_abs = ghost_slot["end_abs"]
                    ghost_active = ghost_slot["ghost_active"]
                    
                    # Get solver values
                    try:
                        is_active = solver.Value(ghost_active)
                        status = "X" if is_active else "O"
                        state = "VACANT" if is_active else "OCCUPIED"
                        
                        # Get streak values
                        active_val = solver.Value(active_streaks[slot_idx]) if slot_idx < len(active_streaks) else "?"
                        vacant_val = solver.Value(vacant_streaks[slot_idx]) if slot_idx < len(vacant_streaks) else "?"
                    except:
                        status = "?"
                        state = "UNKNOWN"
                        active_val = "?"
                        vacant_val = "?"
                    
                    time_range = f"{minutes_to_12hr_time(start_abs)} - {minutes_to_12hr_time(end_abs)}"
                    f.write(f"{time_range:<25} | {status:<6} | {str(active_val):<12} | {str(vacant_val):<12} | {state}\n")
                
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
                f.write(f"{'Time Range':<25} | {'Status':<6} | {'ActiveStreak':<12} | {'VacantStreak':<12} | {'State'}\n")
                f.write(f"{'-'*25} | {'-'*6} | {'-'*12} | {'-'*12} | {'-'*40}\n")
                
                ghost_slots = batch_ghost_grid[(b_idx, day_idx)]
                active_streaks = batch_active_streak.get((b_idx, day_idx), [])
                vacant_streaks = batch_vacant_streak.get((b_idx, day_idx), [])
                
                for slot_idx, ghost_slot in enumerate(ghost_slots):
                    start_abs = ghost_slot["start_abs"]
                    end_abs = ghost_slot["end_abs"]
                    ghost_active = ghost_slot["ghost_active"]
                    
                    # Get solver values
                    try:
                        is_active = solver.Value(ghost_active)
                        status = "X" if is_active else "O"
                        state = "VACANT" if is_active else "OCCUPIED"
                        
                        # Get streak values
                        active_val = solver.Value(active_streaks[slot_idx]) if slot_idx < len(active_streaks) else "?"
                        vacant_val = solver.Value(vacant_streaks[slot_idx]) if slot_idx < len(vacant_streaks) else "?"
                    except:
                        status = "?"
                        state = "UNKNOWN"
                        active_val = "?"
                        vacant_val = "?"
                    
                    time_range = f"{minutes_to_12hr_time(start_abs)} - {minutes_to_12hr_time(end_abs)}"
                    f.write(f"{time_range:<25} | {status:<6} | {str(active_val):<12} | {str(vacant_val):<12} | {state}\n")
                
                f.write("\n")
        
        f.write("\n" + "=" * 120 + "\n")
    
    print(f"[Ghost Grid Debug] {pass_name} exported to: {filepath}")


def print_all_meetings_debug(meetings, assigned_faculty, assigned_room, section_assignments, 
                              faculty, rooms, batches, subjects_map, config, solver,
                              output_dir=None, pass_name=""):
    """
    Exports all meetings (active and inactive) in a scannable table format.
    Each row is a subject/section showing duration for each day.
    
    Args:
        meetings: Dict of (subject_id, section, day) -> meeting info
        assigned_faculty: Dict of (subject_id, section) -> faculty index
        assigned_room: Dict of (subject_id, section) -> room index
        section_assignments: Dict of (subject_id, section, batch_idx) -> student count
        faculty: List of faculty objects
        rooms: List of room objects
        batches: List of batch objects
        subjects_map: Dict of subject_id -> Subject object
        config: Configuration dict
        solver: CP-SAT solver instance
        output_dir: Directory to write file
        pass_name: Name of the pass (e.g., "pass1", "pass2")
    """
    filename = f"all_meetings_{pass_name}.txt" if pass_name else "all_meetings.txt"
    if output_dir:
        filepath = os.path.join(output_dir, filename)
    else:
        filepath = filename
    
    DUMMY_FACULTY_IDX = len(faculty)
    DUMMY_ROOM_IDX = len(rooms)
    
    # Group meetings by subject and section
    meetings_by_section = {}
    for (sub_id, s, d_idx), mtg in meetings.items():
        key = (sub_id, s)
        if key not in meetings_by_section:
            meetings_by_section[key] = {}
        meetings_by_section[key][d_idx] = mtg
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("=" * 180 + "\n")
        f.write(f"ALL MEETINGS OVERVIEW - {pass_name.upper()}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 180 + "\n\n")
        
        # Header
        day_names = config["SCHEDULING_DAYS"]
        f.write(f"{'Subject':>12s} | {'Sec':>3s} | ")
        for day in day_names:
            f.write(f"{day[:3]:>8s} | ")
        f.write(f"{'Faculty':>20s} | {'Status':>6s}\n")
        
        f.write(f"{'-'*12} | {'-'*3} | ")
        for _ in day_names:
            f.write(f"{'-'*8} | ")
        f.write(f"{'-'*20} | {'-'*6}\n")
        
        # Data rows
        total_sections = 0
        sections_with_meetings = 0
        
        for (sub_id, s), day_meetings in sorted(meetings_by_section.items()):
            total_sections += 1
            subject = subjects_map.get(sub_id)
            
            # Get assigned faculty
            faculty_idx = solver.Value(assigned_faculty[(sub_id, s)])
            if faculty_idx == DUMMY_FACULTY_IDX:
                faculty_name = "UNASSIGNED"
            else:
                faculty_name = faculty[faculty_idx].name
            
            # Collect durations for each day
            durations = []
            has_active_meeting = False
            
            for d_idx in range(len(day_names)):
                if d_idx in day_meetings:
                    mtg = day_meetings[d_idx]
                    is_active = solver.Value(mtg["is_active"])
                    
                    if is_active:
                        duration = solver.Value(mtg["duration"])
                        durations.append(duration)
                        has_active_meeting = True
                    else:
                        durations.append(0)
                else:
                    durations.append(0)
            
            if has_active_meeting:
                sections_with_meetings += 1
                status = "has!"
            else:
                status = "none!"
            
            # Write row
            f.write(f"{str(sub_id):>12s} | {s:>3d} | ")
            for dur in durations:
                f.write(f"{dur:>8d} | ")
            f.write(f"{faculty_name:>20s} | {status:>6s}\n")
        
        f.write("\n" + "=" * 180 + "\n")
        
        # Summary statistics
        total_meetings = len(meetings)
        active_meetings = sum(1 for mtg in meetings.values() if solver.Value(mtg["is_active"]) == 1)
        inactive_meetings = total_meetings - active_meetings
        
        f.write(f"\nSUMMARY:\n")
        f.write(f"  Total Sections:           {total_sections}\n")
        f.write(f"  Sections with Meetings:   {sections_with_meetings}\n")
        f.write(f"  Sections without Meetings: {total_sections - sections_with_meetings}\n")
        f.write(f"  Total Meeting Slots:      {total_meetings}\n")
        f.write(f"  Active Meetings:          {active_meetings}\n")
        f.write(f"  Inactive Meetings:        {inactive_meetings}\n")
        f.write(f"\n" + "=" * 180 + "\n")
    
    print(f"[Meeting Debug] {pass_name} exported to: {filepath}")


def export_soft_time_violations_detailed(solver, results, config, faculty, batches, output_dir):
    """
    Export detailed soft time violation reports to separate Excel files.
    Creates one Excel file per violation type with one sheet per entity.
    
    Args:
        solver: CpSolver instance with solution
        results: Results dictionary from run_scheduler
        config: Configuration dictionary
        faculty: List of Faculty objects
        batches: List of Batch objects
        output_dir: Directory to save the Excel files
    """
    import pandas as pd
    from openpyxl import Workbook
    
    violations = results.get("violations", {})
    TIME_GRANULARITY = config.get("TIME_GRANULARITY_MINUTES", 10)
    DAY_START_MINUTES = config.get("DAY_START_MINUTES", 480)
    SCHEDULING_DAYS = config.get("SCHEDULING_DAYS", ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"])
    
    # Calculate penalty per slot
    slots_per_hour = 60 / TIME_GRANULARITY
    under_min_block_penalty_per_slot = int(config["ConstraintPenalties"]["UNDER_MINIMUM_BLOCK_PER_HOUR"] / slots_per_hour)
    excess_gap_penalty_per_slot = int(config["ConstraintPenalties"]["EXCESS_GAP_PER_HOUR"] / slots_per_hour)
    
    def slot_to_time(slot_idx):
        """Convert slot index to time string."""
        total_minutes = DAY_START_MINUTES + (slot_idx * TIME_GRANULARITY)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        period = "AM" if hours < 12 else "PM"
        display_hour = hours % 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour}:{minutes:02d} {period}"
    
    os.makedirs(output_dir, exist_ok=True)
    
    # ========================================================================
    # FACULTY UNDER MINIMUM BLOCK
    # ========================================================================
    faculty_under_min_data = violations.get("faculty_under_minimum_block", {})
    if faculty_under_min_data:
        all_sheets = {}
        for f_idx in sorted(faculty_under_min_data.keys()):
            faculty_obj = faculty[f_idx]
            sheet_name = f"{f_idx}_{faculty_obj.name}"[:31]  # Excel sheet name limit
            
            rows = []
            for day_idx in sorted(faculty_under_min_data[f_idx].keys()):
                day_name = SCHEDULING_DAYS[day_idx] if day_idx < len(SCHEDULING_DAYS) else f"Day{day_idx}"
                
                for slot_idx, var in enumerate(faculty_under_min_data[f_idx][day_idx]):
                    violation_value = solver.Value(var)
                    if violation_value > 0:
                        penalty = violation_value * under_min_block_penalty_per_slot
                        rows.append({
                            "Faculty ID": f_idx,
                            "Faculty Name": faculty_obj.name,
                            "Day Index": day_idx,
                            "Day Name": day_name,
                            "Slot Index": slot_idx,
                            "Start Time": slot_to_time(slot_idx),
                            "Violation (slots)": violation_value,
                            "Penalty Points": penalty
                        })
            
            if rows:
                all_sheets[sheet_name] = pd.DataFrame(rows)
        
        if all_sheets:
            filepath = os.path.join(output_dir, "faculty_under_minimum_block_detailed.xlsx")
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                for sheet_name, df in all_sheets.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"[Soft Violations] Faculty under minimum block exported to: {filepath}")
        else:
            print(f"[Soft Violations] Faculty under minimum block: No violations found")
    
    # ========================================================================
    # FACULTY EXCESS GAPS
    # ========================================================================
    faculty_excess_gaps_data = violations.get("faculty_excess_gaps", {})
    if faculty_excess_gaps_data:
        all_sheets = {}
        for f_idx in sorted(faculty_excess_gaps_data.keys()):
            faculty_obj = faculty[f_idx]
            sheet_name = f"{f_idx}_{faculty_obj.name}"[:31]
            
            rows = []
            for day_idx in sorted(faculty_excess_gaps_data[f_idx].keys()):
                day_name = SCHEDULING_DAYS[day_idx] if day_idx < len(SCHEDULING_DAYS) else f"Day{day_idx}"
                
                for slot_idx, var in enumerate(faculty_excess_gaps_data[f_idx][day_idx]):
                    violation_value = solver.Value(var)
                    if violation_value > 0:
                        penalty = violation_value * excess_gap_penalty_per_slot
                        rows.append({
                            "Faculty ID": f_idx,
                            "Faculty Name": faculty_obj.name,
                            "Day Index": day_idx,
                            "Day Name": day_name,
                            "Slot Index": slot_idx,
                            "Start Time": slot_to_time(slot_idx),
                            "Violation (slots)": violation_value,
                            "Penalty Points": penalty
                        })
            
            if rows:
                all_sheets[sheet_name] = pd.DataFrame(rows)
        
        if all_sheets:
            filepath = os.path.join(output_dir, "faculty_excess_gaps_detailed.xlsx")
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                for sheet_name, df in all_sheets.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"[Soft Violations] Faculty excess gaps exported to: {filepath}")
        else:
            print(f"[Soft Violations] Faculty excess gaps: No violations found")
    
    # ========================================================================
    # BATCH UNDER MINIMUM BLOCK
    # ========================================================================
    batch_under_min_data = violations.get("batch_under_minimum_block", {})
    if batch_under_min_data:
        all_sheets = {}
        for b_idx in sorted(batch_under_min_data.keys()):
            batch_obj = batches[b_idx]
            sheet_name = f"{b_idx}_{batch_obj.batch_id}"[:31]
            
            rows = []
            for day_idx in sorted(batch_under_min_data[b_idx].keys()):
                day_name = SCHEDULING_DAYS[day_idx] if day_idx < len(SCHEDULING_DAYS) else f"Day{day_idx}"
                
                for slot_idx, var in enumerate(batch_under_min_data[b_idx][day_idx]):
                    violation_value = solver.Value(var)
                    if violation_value > 0:
                        penalty = violation_value * under_min_block_penalty_per_slot
                        rows.append({
                            "Batch ID": b_idx,
                            "Batch Name": batch_obj.batch_id,
                            "Day Index": day_idx,
                            "Day Name": day_name,
                            "Slot Index": slot_idx,
                            "Start Time": slot_to_time(slot_idx),
                            "Violation (slots)": violation_value,
                            "Penalty Points": penalty
                        })
            
            if rows:
                all_sheets[sheet_name] = pd.DataFrame(rows)
        
        if all_sheets:
            filepath = os.path.join(output_dir, "batch_under_minimum_block_detailed.xlsx")
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                for sheet_name, df in all_sheets.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"[Soft Violations] Batch under minimum block exported to: {filepath}")
        else:
            print(f"[Soft Violations] Batch under minimum block: No violations found")
    
    # ========================================================================
    # BATCH EXCESS GAPS
    # ========================================================================
    batch_excess_gaps_data = violations.get("batch_excess_gaps", {})
    if batch_excess_gaps_data:
        all_sheets = {}
        for b_idx in sorted(batch_excess_gaps_data.keys()):
            batch_obj = batches[b_idx]
            sheet_name = f"{b_idx}_{batch_obj.batch_id}"[:31]
            
            rows = []
            for day_idx in sorted(batch_excess_gaps_data[b_idx].keys()):
                day_name = SCHEDULING_DAYS[day_idx] if day_idx < len(SCHEDULING_DAYS) else f"Day{day_idx}"
                
                for slot_idx, var in enumerate(batch_excess_gaps_data[b_idx][day_idx]):
                    violation_value = solver.Value(var)
                    if violation_value > 0:
                        penalty = violation_value * excess_gap_penalty_per_slot
                        rows.append({
                            "Batch ID": b_idx,
                            "Batch Name": batch_obj.batch_id,
                            "Day Index": day_idx,
                            "Day Name": day_name,
                            "Slot Index": slot_idx,
                            "Start Time": slot_to_time(slot_idx),
                            "Violation (slots)": violation_value,
                            "Penalty Points": penalty
                        })
            
            if rows:
                all_sheets[sheet_name] = pd.DataFrame(rows)
        
        if all_sheets:
            filepath = os.path.join(output_dir, "batch_excess_gaps_detailed.xlsx")
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                for sheet_name, df in all_sheets.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"[Soft Violations] Batch excess gaps exported to: {filepath}")
        else:
            print(f"[Soft Violations] Batch excess gaps: No violations found")
