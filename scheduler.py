# scheduler.py
import collections
import os
import pandas as pd
import random
import time
from datetime import datetime
from ortools.sat.python import cp_model
import math
from collections import defaultdict

# ============================================================================
# SOLVER DIAGNOSTICS CONFIGURATION
# ============================================================================
ENABLE_SOLVER_DIAGNOSTICS = False  # Set to False to disable diagnostic output

# ============================================================================
# SOLVER LOGGING CONFIGURATION (Granular Control)
# ============================================================================
# Each toggle controls a specific phase of the solver's activity
SHOW_MODEL_STATISTICS = True       # Print model size (variables, constraints) before solving
SHOW_PRESOLVE_LOGS = True          # Show presolve phase (constraint propagation, simplification)
SHOW_SEARCH_LOGS = True            # Show search phase (branching, conflicts, restarts)
SHOW_SOLUTION_LOGS = True          # Show when intermediate solutions are found
SHOW_OPTIMIZATION_LOGS = True      # Show detailed progress during solution improvement
# ============================================================================

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

class SolutionPrinterCallback(cp_model.CpSolverSolutionCallback):
    """Prints intermediate solutions with progress metrics and logs to file."""

    def __init__(self, total_penalty, log_file_path=None):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self.__solution_count = 0
        self.__total_penalty = total_penalty
        self.__previous_penalty = None
        self.__last_solution_time = None
        self.__start_time = time.time()
        self.__log_file_path = log_file_path
        # Track solver statistics over time
        self.__last_branches = 0
        self.__last_conflicts = 0
        self.__stats_history = []  # List of (time, branches, conflicts, penalty, gap)

        if self.__log_file_path:
            os.makedirs(os.path.dirname(self.__log_file_path), exist_ok=True)
            with open(self.__log_file_path, "w", encoding="utf-8") as log_file:
                log_file.write("=== Solution Log ===\n")
                log_file.write(f"Started: {datetime.now().isoformat()}\n")
                log_file.write("--------------------\n")

    def on_solution_callback(self):
        self.__solution_count += 1
        current_penalty = self.Value(self.__total_penalty)
        current_time = time.time()
        
        elapsed_total = current_time - self.__start_time
        
        # Get current solver statistics
        current_branches = self.NumBranches()
        current_conflicts = self.NumConflicts()
        current_bound = self.BestObjectiveBound()
        current_gap = abs(current_penalty - current_bound) if current_bound else 0
        gap_percent = (current_gap / max(abs(current_penalty), 1)) * 100 if current_penalty != 0 else 0
        
        hours = int(elapsed_total // 3600)
        minutes = int((elapsed_total % 3600) // 60)
        seconds = int(elapsed_total % 60)

        time_parts = []
        if hours > 0:
            time_parts.append(f"{hours}h")
        if minutes > 0:
            time_parts.append(f"{minutes}m")
        time_parts.append(f"{seconds}s")  # always show seconds

        elapsed_str = " ".join(time_parts)

        output = f"Solution {self.__solution_count}, penalty = {current_penalty}, time = {elapsed_str}"
        
        # Calculate delta statistics since last solution
        delta_branches = current_branches - self.__last_branches
        delta_conflicts = current_conflicts - self.__last_conflicts
        
        if self.__previous_penalty is not None and self.__last_solution_time is not None:
            penalty_decrease = self.__previous_penalty - current_penalty
            time_diff = current_time - self.__last_solution_time
            ratio = penalty_decrease / time_diff if time_diff > 0 else 0
            branches_per_sec = delta_branches / time_diff if time_diff > 0 else 0
            conflicts_per_sec = delta_conflicts / time_diff if time_diff > 0 else 0
            output += f' (↓{penalty_decrease} in {time_diff:.1f}s, ratio: {ratio:.1f}/s)'
            output += f' | br/s: {branches_per_sec:,.0f}, cf/s: {conflicts_per_sec:,.0f}, gap: {gap_percent:.1f}%'
        else:
            output += f' | gap: {gap_percent:.1f}%'
        
        print(output)

        if self.__log_file_path:
            with open(self.__log_file_path, "a", encoding="utf-8") as log_file:
                log_file.write(output + "\n")
        
        # Store statistics for analysis
        self.__stats_history.append({
            'time': elapsed_total,
            'solution': self.__solution_count,
            'penalty': current_penalty,
            'gap': current_gap,
            'gap_percent': gap_percent,
            'total_branches': current_branches,
            'total_conflicts': current_conflicts,
            'delta_branches': delta_branches,
            'delta_conflicts': delta_conflicts,
        })

        self.__previous_penalty = current_penalty
        self.__last_solution_time = current_time
        self.__last_branches = current_branches
        self.__last_conflicts = current_conflicts

    def solution_count(self):
        return self.__solution_count
    
    def get_stats_history(self):
        """Return the statistics history for post-solve analysis."""
        return self.__stats_history
    
    def write_stats_summary(self, output_path=None):
        """Write a summary of solver statistics over time to file."""
        if not self.__stats_history:
            return
        
        path = output_path or (self.__log_file_path.replace('.txt', '_stats.txt') if self.__log_file_path else 'solver_stats.txt')
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write("=" * 120 + "\n")
            f.write("SOLVER STATISTICS OVER TIME\n")
            f.write("=" * 120 + "\n\n")
            
            f.write(f"{'Sol#':>5} | {'Time':>8} | {'Penalty':>10} | {'Gap%':>7} | {'Δ Branches':>12} | {'Δ Conflicts':>12} | {'Br/s':>10} | {'Cf/s':>10}\n")
            f.write("-" * 120 + "\n")
            
            prev_time = 0
            for s in self.__stats_history:
                time_diff = s['time'] - prev_time
                br_per_sec = s['delta_branches'] / time_diff if time_diff > 0 else 0
                cf_per_sec = s['delta_conflicts'] / time_diff if time_diff > 0 else 0
                
                f.write(f"{s['solution']:>5} | {s['time']:>7.1f}s | {s['penalty']:>10,} | {s['gap_percent']:>6.1f}% | {s['delta_branches']:>12,} | {s['delta_conflicts']:>12,} | {br_per_sec:>10,.0f} | {cf_per_sec:>10,.0f}\n")
                prev_time = s['time']
            
            f.write("\n" + "=" * 120 + "\n")
            f.write("PHASE ANALYSIS\n")
            f.write("=" * 120 + "\n\n")
            
            # Analyze phases by branch rate
            early = [s for s in self.__stats_history if s['time'] < 120]  # First 2 min
            mid = [s for s in self.__stats_history if 120 <= s['time'] < 300]  # 2-5 min
            late = [s for s in self.__stats_history if s['time'] >= 300]  # 5+ min
            
            def avg_rate(stats, key):
                if not stats or len(stats) < 2:
                    return 0
                total_delta = sum(s[key] for s in stats[1:])  # Skip first (no delta)
                total_time = stats[-1]['time'] - stats[0]['time']
                return total_delta / total_time if total_time > 0 else 0
            
            f.write(f"Early phase (0-2min):   {len(early):>3} solutions, avg {avg_rate(early, 'delta_branches'):>10,.0f} br/s, {avg_rate(early, 'delta_conflicts'):>10,.0f} cf/s\n")
            f.write(f"Middle phase (2-5min):  {len(mid):>3} solutions, avg {avg_rate(mid, 'delta_branches'):>10,.0f} br/s, {avg_rate(mid, 'delta_conflicts'):>10,.0f} cf/s\n")
            f.write(f"Late phase (5min+):     {len(late):>3} solutions, avg {avg_rate(late, 'delta_branches'):>10,.0f} br/s, {avg_rate(late, 'delta_conflicts'):>10,.0f} cf/s\n")
            
            # Identify slowdown patterns
            f.write("\n" + "-" * 120 + "\n")
            f.write("SLOWDOWN INDICATORS:\n")
            
            if late and early:
                early_rate = avg_rate(early, 'delta_branches')
                late_rate = avg_rate(late, 'delta_branches')
                if early_rate > 0 and late_rate > 0:
                    slowdown = early_rate / late_rate
                    f.write(f"   Branch rate slowdown: {slowdown:.1f}x slower in late phase\n")
                    
                    if slowdown > 10:
                        f.write("   [CRITICAL] Severe slowdown - likely hitting propagation bottleneck\n")
                    elif slowdown > 3:
                        f.write("   [WARNING] Significant slowdown - solver struggling with harder subproblems\n")
                    else:
                        f.write("   [OK] Normal slowdown as search space narrows\n")
            
            # Check for plateau (many solutions with small improvements)
            if len(self.__stats_history) > 10:
                last_10 = self.__stats_history[-10:]
                avg_improvement = sum(
                    (last_10[i-1]['penalty'] - last_10[i]['penalty']) 
                    for i in range(1, len(last_10))
                ) / (len(last_10) - 1)
                time_span = last_10[-1]['time'] - last_10[0]['time']
                
                f.write(f"\n   Last 10 solutions: avg improvement {avg_improvement:.0f} over {time_span:.0f}s\n")
                if avg_improvement < 100 and time_span > 60:
                    f.write("   [WARNING] Plateau detected - small improvements taking long time\n")
                    f.write("   Consider: symmetry breaking, LNS parameters, or objective decomposition\n")
        
        print(f"[Stats] Detailed statistics written to: {path}")


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


def print_raw_violations(solver, results, faculty, batches, config, print_to_terminal=True, save_to_file=True, filename="violations_report.xlsx"):
    """
    Analyzes and reports all constraint violations in two categories:
    1. STRUCTURAL VIOLATIONS (boolean slack variables from Pass 1)
    2. SOFT CONSTRAINT PENALTIES (integer penalty trackers from Pass 2)
    
    - Terminal output shows RAW values of ALL indexes (not just violations)
    - File output is a multi-sheet Excel file for data analysis
    
    Args:
        solver: CpSolver instance used for evaluation
        results: dictionary returned by run_scheduler containing violations
        faculty: list of Faculty objects
        batches: list of Batch objects
        config: scheduler configuration dictionary (used for slot-to-time conversion)
        print_to_terminal: toggle terminal output
        save_to_file: toggle excel output
        filename: excel filename
    """
    if not print_to_terminal and not save_to_file:
        print("Violation report generation skipped as both terminal and file outputs are disabled.")
        return

    structural_terminal_lines = []
    soft_terminal_lines = []
    structural_excel_data = collections.defaultdict(list)
    soft_excel_data = collections.defaultdict(list)
    
    if config is None:
        raise ValueError("config is required to translate slot indices to time.")

    violations = results.get("violations", {})
    
    # Get dummy indices for structural violation reporting
    DUMMY_FACULTY_IDX = results.get("DUMMY_FACULTY_IDX")
    DUMMY_ROOM_IDX = results.get("DUMMY_ROOM_IDX")

    SLOT_SIZE = 10  # minutes per slot
    day_start_minutes = config.get("DAY_START_MINUTES", 0)

    def slot_to_time(slot_idx):
        total_minutes = day_start_minutes + slot_idx * SLOT_SIZE
        hours = total_minutes // 60
        minutes = total_minutes % 60
        period = "AM" if hours % 24 < 12 else "PM"
        display_hour = hours % 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour}:{minutes:02d} {period}"

    # ============================================================================
    # SECTION 1: STRUCTURAL VIOLATIONS (Boolean Slack Variables from Pass 1)
    # ============================================================================
    
    # 1a. Unassigned Faculty (Dummy Faculty Assignments)
    v_type = "is_dummy_faculty"
    dummy_faculty_data = violations.get("is_dummy_faculty", {})
    for (sub_id, s_idx), var in sorted(dummy_faculty_data.items()):
        if hasattr(var, 'Proto'):
            value = solver.Value(var)
            structural_terminal_lines.append(f"{v_type}: (sub: '{sub_id}', sec: {s_idx}) = {value}")
            structural_excel_data[v_type].append({"subject_id": sub_id, "section_idx": s_idx, "value": value})
    
    # 1b. Unassigned Room (Dummy Room Assignments)
    v_type = "is_dummy_room"
    dummy_room_data = violations.get("is_dummy_room", {})
    for (sub_id, s_idx), var in sorted(dummy_room_data.items()):
        if hasattr(var, 'Proto'):
            value = solver.Value(var)
            structural_terminal_lines.append(f"{v_type}: (sub: '{sub_id}', sec: {s_idx}) = {value}")
            structural_excel_data[v_type].append({"subject_id": sub_id, "section_idx": s_idx, "value": value})
    
    # 1c. Duration Violations (Weekly Hours Shortfall)
    v_type = "duration_violations"
    duration_data = violations.get("duration_violations", {})
    for (sub_id, s_idx), var in sorted(duration_data.items()):
        if hasattr(var, 'Proto'):
            value = solver.Value(var)
            structural_terminal_lines.append(f"{v_type}: (sub: '{sub_id}', sec: {s_idx}) = {value}")
            structural_excel_data[v_type].append({"subject_id": sub_id, "section_idx": s_idx, "value": value})
    
    # 1d. Faculty Day Gaps (structural slack)
    v_type = "faculty_day_gaps"
    faculty_day_gap_data = violations.get("faculty_day_gaps", {})
    for f_idx, flag_list in sorted(faculty_day_gap_data.items()):
        for day_offset, var in enumerate(flag_list):
            if hasattr(var, 'Proto'):
                value = solver.Value(var)
                # day_offset 0 = day 1 (Tuesday), day_offset 1 = day 2 (Wednesday), day_offset 2 = day 3 (Thursday)
                actual_day = day_offset + 1
                structural_terminal_lines.append(f"{v_type}: (f: {f_idx}, day: {actual_day}) = {value}")
                structural_excel_data[v_type].append({"faculty_idx": f_idx, "day_idx": actual_day, "value": value})
    
    # 1e. Batch Day Gaps (structural slack)
    v_type = "batch_day_gaps"
    batch_day_gap_data = violations.get("batch_day_gaps", {})
    for b_idx, flag_list in sorted(batch_day_gap_data.items()):
        for day_offset, var in enumerate(flag_list):
            if hasattr(var, 'Proto'):
                value = solver.Value(var)
                actual_day = day_offset + 1
                structural_terminal_lines.append(f"{v_type}: (b: {b_idx}, day: {actual_day}) = {value}")
                structural_excel_data[v_type].append({"batch_idx": b_idx, "day_idx": actual_day, "value": value})

    # ============================================================================
    # SECTION 2: SOFT CONSTRAINT PENALTIES (Integer Penalty Trackers from Pass 2)
    # ============================================================================
    
    # 2a. Faculty Overload (minutes over max)
    v_type = "faculty_overload"
    for f_idx, var in enumerate(violations.get("faculty_overload", [])):
        value = solver.Value(var)
        soft_terminal_lines.append(f"{v_type}: (f: {f_idx}) = {value}")
        soft_excel_data[v_type].append({"faculty_idx": f_idx, "value": value})
    
    # 2a2. Faculty Underfill (minutes under min)
    v_type = "faculty_underfill"
    for f_idx, var in enumerate(violations.get("faculty_underfill", [])):
        value = solver.Value(var)
        soft_terminal_lines.append(f"{v_type}: (f: {f_idx}) = {value}")
        soft_excel_data[v_type].append({"faculty_idx": f_idx, "value": value})

    # 2b. Room Overcapacity
    v_type = "room_overcapacity"
    for (sub_id, s_idx), var in sorted(violations.get("room_overcapacity", {}).items()):
        value = solver.Value(var)
        soft_terminal_lines.append(f"{v_type}: (sub: '{sub_id}', sec: {s_idx}) = {value}")
        soft_excel_data[v_type].append({"subject_id": sub_id, "section_idx": s_idx, "value": value})

    # 2c. Section Overfill
    v_type = "section_overfill"
    for (sub_id, s_idx), var in sorted(violations.get("section_overfill", {}).items()):
        value = solver.Value(var)
        soft_terminal_lines.append(f"{v_type}: (sub: '{sub_id}', sec: {s_idx}) = {value}")
        soft_excel_data[v_type].append({"subject_id": sub_id, "section_idx": s_idx, "value": value})

    # 2d. Section Underfill
    v_type = "section_underfill"
    for (sub_id, s_idx), var in sorted(violations.get("section_underfill", {}).items()):
        value = solver.Value(var)
        soft_terminal_lines.append(f"{v_type}: (sub: '{sub_id}', sec: {s_idx}) = {value}")
        soft_excel_data[v_type].append({"subject_id": sub_id, "section_idx": s_idx, "value": value})

    # 2e. Nested soft constraint violations (continuous class, gaps, minimum blocks, non-preferred)
    nested_soft_violations = {
        "faculty_excess_gaps": violations.get("faculty_excess_gaps", {}),
        "batch_excess_gaps": violations.get("batch_excess_gaps", {}),
        "faculty_under_minimum_block": violations.get("faculty_under_minimum_block", {}),
        "batch_under_minimum_block": violations.get("batch_under_minimum_block", {}),
    }

    for v_type, data in sorted(nested_soft_violations.items()):
        for entity_idx, day_data in sorted(data.items()):
            for day_idx, slot_vars in sorted(day_data.items()):
                for slot_idx, var in enumerate(slot_vars):
                    if hasattr(var, 'Proto'):
                        value = solver.Value(var)
                        soft_terminal_lines.append(f"{v_type}: (e: {entity_idx}, d: {day_idx}, s: {slot_idx}) = {value}")
                        soft_excel_data[v_type].append({
                            "entity_idx": entity_idx,
                            "day_idx": day_idx,
                            "slot_idx": slot_idx,
                            "slot_time": slot_to_time(slot_idx),
                            "value": value
                        })

    # 2f. Non-preferred subject assignments (special nested structure: f_idx -> sub_id -> list)
    v_type = "faculty_non_preferred_subject"
    non_pref_data = violations.get("faculty_non_preferred_subject", {})
    for f_idx, sub_data in sorted(non_pref_data.items()):
        for sub_id, var_list in sorted(sub_data.items()):
            for sec_idx, var in enumerate(var_list):
                if hasattr(var, 'Proto'):
                    value = solver.Value(var)
                    soft_terminal_lines.append(f"{v_type}: (f: {f_idx}, sub: '{sub_id}', sec: {sec_idx}) = {value}")
                    soft_excel_data[v_type].append({
                        "faculty_idx": f_idx,
                        "subject_id": sub_id,
                        "section_idx": sec_idx,
                        "value": value
                    })

    # ============================================================================
    # OUTPUT GENERATION
    # ============================================================================
    
    if save_to_file:
        # Save structural violations to separate file
        structural_filename = filename.replace(".xlsx", "_structural.xlsx")
        soft_filename = filename.replace(".xlsx", "_soft.xlsx")
        
        if structural_excel_data:
            try:
                with pd.ExcelWriter(structural_filename, engine='openpyxl') as writer:
                    for v_type, records in sorted(structural_excel_data.items()):
                        df = pd.DataFrame(records)
                        safe_sheet_name = v_type.replace('_', ' ').title()[:31]
                        df.to_excel(writer, sheet_name=safe_sheet_name, index=False)
                print(f"\n✓ Structural violations saved to: {structural_filename}")
            except Exception as e:
                print(f"\n❌ Error saving structural violations: {e}")
        else:
            print("\nNo structural violation data to save.")
        
        if soft_excel_data:
            try:
                with pd.ExcelWriter(soft_filename, engine='openpyxl') as writer:
                    for v_type, records in sorted(soft_excel_data.items()):
                        df = pd.DataFrame(records)
                        safe_sheet_name = v_type.replace('_', ' ').title()[:31]
                        df.to_excel(writer, sheet_name=safe_sheet_name, index=False)
                print(f"✓ Soft constraint penalties saved to: {soft_filename}")
            except Exception as e:
                print(f"\n❌ Error saving soft constraint penalties: {e}")
        else:
            print("No soft constraint penalty data to save.")

    if print_to_terminal:
        # Print structural violations
        print("\n" + "="*70)
        print("--- RAW STRUCTURAL VIOLATIONS (Boolean Slack Variables - Pass 1) ---")
        print("="*70)
        if not structural_terminal_lines:
            print("No structural slack variables found.")
        else:
            for line in structural_terminal_lines:
                print(line)
        
        # Count actual violations
        structural_violation_count = sum(1 for line in structural_terminal_lines if "= 1" in line)
        print(f"\nTotal structural violations (value=1): {structural_violation_count}")
        print("="*70)
        
        # Print soft constraint penalties
        print("\n" + "="*70)
        print("--- RAW SOFT CONSTRAINT PENALTIES (Integer Trackers - Pass 2) ---")
        print("="*70)
        if not soft_terminal_lines:
            print("No soft constraint penalty trackers found.")
        else:
            for line in soft_terminal_lines:
                print(line)
        
        # Count non-zero penalties
        soft_violation_count = sum(1 for line in soft_terminal_lines if not line.endswith("= 0"))
        print(f"\nTotal non-zero soft penalties: {soft_violation_count}")
        print("="*70)

def run_scheduler(config, subjects, rooms, faculty, batches, subjects_map, time_limit=None, random_seed=None, deterministic_mode=False, output_folder=None, pass_mode="full", structural_limit=None, pass1_hints=None):
    """
    Main function to build and solve the scheduling model.
    
    Args:
        config: Configuration dictionary
        subjects: List of Subject objects
        rooms: List of Room objects
        faculty: List of Faculty objects
        batches: List of Batch objects
        subjects_map: Dictionary mapping subject_id to Subject objects
        time_limit: Maximum time in seconds for solving
        random_seed: Random seed for reproducibility
        deterministic_mode: If True, enforces deterministic behavior by using single-threaded
                          solver and sorting all dictionary iterations. Default False.
        output_folder: Path to folder where solution logs should be saved. If None, uses default reports folder.
        pass_mode: "pass1" (structural only), "pass2" (preferences), or "full" (legacy). Default "full".
        structural_limit: Required when pass_mode="pass2", the minimum structural violations from pass1.
        pass1_hints: Optional dict of solution values from Pass 1 to seed Pass 2 solver with AddHint.
    """
    
    # PASS_MODE GATE: Controls whether soft constraints are built
    # pass1: minimal model (no soft constraints) for fast structural optimization
    # pass2/full: full model with all soft constraints
    build_soft_constraints = pass_mode in ["pass2", "full"]
    
    # TIME GRANULARITY: Controls time interval precision (10 or 30 minutes)
    TIME_GRANULARITY = config.get("TIME_GRANULARITY_MINUTES", 10)
    if TIME_GRANULARITY not in [10, 30]:
        raise ValueError(f"TIME_GRANULARITY_MINUTES must be 10 or 30, got {TIME_GRANULARITY}")
    
    print(f"⏱️  Time Granularity: {TIME_GRANULARITY} minutes")
    
    model = cp_model.CpModel()

#================================== START OF VARIABLE CREATION [VARIABLES/REIFICATION] ==================================
    
    # [VARIABLES] Core data structures and IntVars
    meetings = {}
    assigned_faculty = {}
    assigned_room = {}
    section_assignments = {}
    intervals_per_faculty = collections.defaultdict(list)
    intervals_per_batch = collections.defaultdict(list)
    # NOTE: faculty_slot_meetings and batch_slot_meetings removed - DRS approach doesn't need them
    
    # Dummy indices represent "unassigned" states (structural violation if used)
    DUMMY_FACULTY_IDX = len(faculty)
    DUMMY_ROOM_IDX = len(rooms)
    
    is_dummy_faculty = {}  # (subject_id, section) -> BoolVar
    is_dummy_room = {}     # (subject_id, section) -> BoolVar
    duration_violations = {}  # (subject_id, section) -> BoolVar

    # Pre-compute qualified faculty and rooms per subject
    subject_qualified_faculty = {}
    subject_possible_rooms = {}
    for sub in subjects:
        subject_qualified_faculty[sub.subject_id] = [
            f_idx for f_idx, f in enumerate(faculty) 
            if sub.subject_id in f.qualified_subject_ids
        ]
        subject_possible_rooms[sub.subject_id] = [
            r_idx for r_idx, r in enumerate(rooms) 
            if r.room_type_id == sub.room_type_id
        ]
    
    # Helper function to detect lab subjects
    def is_lab_subject(sub):
        """
        Check if subject is a lab that requires linked lecture constraints.
        Returns True if subject has linked_subject_id AND subject_type name contains "Lab".
        """
        if not sub.linked_subject_id:
            return False
        subject_type_name = getattr(sub, '_subject_type_name', '') or ''
        return 'lab' in subject_type_name.lower()

    faculty_qualified_subjects = {
        f_idx: [
            subjects_map[sub_id]
            for sub_id in sorted(f.qualified_subject_ids)
            if sub_id in subjects_map
        ]
        for f_idx, f in enumerate(faculty)
    }

    # Pre-compute day end times
    MINUTES_IN_A_DAY = 1440
    FRIDAY_IDX = 4
    day_end_times = [
        config["FRIDAY_END_MINUTES"] if d_idx == FRIDAY_IDX 
        else config["DAY_END_MINUTES"]
        for d_idx in range(len(config["SCHEDULING_DAYS"]))
    ]

    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            key = (sub.subject_id, s)
            
            # Faculty assignment with dummy fallback
            qualified_faculty_indices = subject_qualified_faculty[sub.subject_id]
            assigned_faculty[key] = model.NewIntVar(0, DUMMY_FACULTY_IDX, f"faculty_{sub.subject_id}_s{s}")
            allowed_faculty = qualified_faculty_indices + [DUMMY_FACULTY_IDX]
            model.AddAllowedAssignments([assigned_faculty[key]], [(idx,) for idx in allowed_faculty])
            
            # [REIFICATION] Track if dummy faculty is assigned
            is_dummy_fac = model.NewBoolVar(f"is_dummy_faculty_{sub.subject_id}_s{s}")
            model.Add(assigned_faculty[key] == DUMMY_FACULTY_IDX).OnlyEnforceIf(is_dummy_fac)
            model.Add(assigned_faculty[key] != DUMMY_FACULTY_IDX).OnlyEnforceIf(is_dummy_fac.Not())
            is_dummy_faculty[key] = is_dummy_fac
            
            # Batch population assignment
            for b_idx, b in enumerate(batches):
                if any(subj.subject_id == sub.subject_id for subj in b.subjects):
                    section_assignments[(sub.subject_id, s, b_idx)] = model.NewIntVar(
                        0, b.population, f"assign_{sub.subject_id}_s{s}_b{b_idx}"
                    )
            
            # Room assignment per SECTION (shared across all days, reduces variables 5x)
            possible_room_indices = subject_possible_rooms[sub.subject_id]
            assigned_room[key] = model.NewIntVar(0, DUMMY_ROOM_IDX, f"room_{sub.subject_id}_s{s}")
            allowed_rooms = possible_room_indices + [DUMMY_ROOM_IDX]
            model.AddAllowedAssignments([assigned_room[key]], [(idx,) for idx in allowed_rooms])
            
            # [REIFICATION] Track if dummy room is assigned
            is_dummy_rm = model.NewBoolVar(f"is_dummy_room_{sub.subject_id}_s{s}")
            model.Add(assigned_room[key] == DUMMY_ROOM_IDX).OnlyEnforceIf(is_dummy_rm)
            model.Add(assigned_room[key] != DUMMY_ROOM_IDX).OnlyEnforceIf(is_dummy_rm.Not())
            is_dummy_room[key] = is_dummy_rm
            
            # Meeting variables
            for d_idx in range(len(config["SCHEDULING_DAYS"])):
                meeting_key = (sub.subject_id, s, d_idx)
                day_offset = d_idx * MINUTES_IN_A_DAY
                end_minutes = day_end_times[d_idx]
                
                # OPTIMIZATION: Domain restricted to TIME_GRANULARITY intervals
                day_start = config["DAY_START_MINUTES"] + day_offset
                day_end = end_minutes + day_offset
                start_domain = cp_model.Domain.FromValues(range(day_start, day_end + 1, TIME_GRANULARITY))
                start_var = model.NewIntVarFromDomain(start_domain, f"start_{sub.subject_id}_s{s}_d{d_idx}")
                
                # Calculate duration domain from min/max meetings
                # Duration domain = {0} ∪ {required / n for n in range(min_meetings, max_meetings + 1)}
                # Note: Don't restrict to discrete values - allow flexible durations for solver
                if sub.max_meetings == 0:
                    # Subject has no meetings - only 0 is allowed
                    max_duration = 0
                    use_discrete_durations = True
                    allowed_duration_values = [0]
                elif sub.min_meetings and sub.max_meetings:
                    # Build discrete duration values by iterating from min_meetings to max_meetings.
                    # For each n in [min, max], duration = floor(total / n). Include duration if >= 60.
                    # Stop iterating once duration falls below 60; include 60 and then stop.
                    # Note: No need to include 0 - optional intervals handle inactive state without it
                    allowed_duration_values = []
                    max_duration = 0
                    for n in range(sub.min_meetings, sub.max_meetings + 1):
                        d = sub.required_weekly_minutes // n
                        if d >= 60:
                            if d not in allowed_duration_values:
                                allowed_duration_values.append(d)
                            max_duration = max(max_duration, d)
                            if d == 60:
                                break
                        else:
                            # Further n will only decrease d, so break out
                            break
                    use_discrete_durations = True
                else:
                    # No min/max defined — require explicit min/max values
                    raise ValueError(
                        f"Subject {sub.subject_id} (required_weekly_minutes={sub.required_weekly_minutes}) "
                        "must define both 'min_meetings' and 'max_meetings'. The fallback behavior was removed; "
                        "provide explicit min/max meetings (integers) so valid duration domains can be computed."
                    )
                
                duration_var = model.NewIntVar(0, max_duration, f"duration_{sub.subject_id}_s{s}_d{d_idx}")
                
                # Restrict to allowed discrete values only if specified
                if use_discrete_durations and allowed_duration_values:
                    model.AddAllowedAssignments([duration_var], [(d,) for d in allowed_duration_values])
                
                end_domain = cp_model.Domain.FromValues(range(day_start, day_end + 1, TIME_GRANULARITY))
                end_var = model.NewIntVarFromDomain(end_domain, f"end_{sub.subject_id}_s{s}_d{d_idx}")
                is_active = model.NewBoolVar(f"is_active_{sub.subject_id}_s{s}_d{d_idx}")
                
                interval_var = model.NewOptionalIntervalVar(
                    start_var, duration_var, end_var, is_active,
                    f"interval_{sub.subject_id}_s{s}_d{d_idx}"
                )
                
                meetings[meeting_key] = {
                    "start": start_var,
                    "duration": duration_var,
                    "end": end_var,
                    "is_active": is_active,
                    "interval": interval_var
                }
                
                # Force meeting inactive if dummy faculty or dummy room
                model.Add(is_active == 0).OnlyEnforceIf(is_dummy_fac)
                model.Add(is_active == 0).OnlyEnforceIf(is_dummy_rm)

#================================== END OF VARIABLE CREATION ==================================

#================================== START OF ZERO-MEETING SUBJECTS [HARD] ==================================
    # [HARD] Force subjects with max_meetings=0 to have no active meetings
    for sub in subjects:
        if sub.max_meetings == 0:
            for s in range(sub.ideal_num_sections):
                for d_idx in range(len(config["SCHEDULING_DAYS"])):
                    mtg = meetings[(sub.subject_id, s, d_idx)]
                    model.Add(mtg["is_active"] == 0)
                    model.Add(mtg["duration"] == 0)
#================================== END OF ZERO-MEETING SUBJECTS ==================================

#================================== START OF REUSABLE ASSIGNMENT STORAGE [REIFICATION] ==================================
    # Build once, reuse across no-overlap and slot-linking sections
    is_assigned_faculty_map = {}   # key: (f_idx, sub_id, s) -> BoolVar
    is_assigned_room_map = {}      # key: (r_idx, sub_id, s) -> BoolVar
    is_assigned_batch_map = {}     # key: (b_idx, sub_id, s) -> BoolVar

    # Activation boolean maps (entity assigned AND meeting active)
    active_for_faculty_map = {}    # key: (f_idx, sub_id, s, d_idx) -> BoolVar
    active_for_room_map = {}       # key: (r_idx, sub_id, s, d_idx) -> BoolVar
    active_for_batch_map = {}      # key: (b_idx, sub_id, s, d_idx) -> BoolVar

    # Faculty assignment booleans
    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            qualified_faculty_indices = subject_qualified_faculty[sub.subject_id]
            for f_idx in qualified_faculty_indices:
                b = model.NewBoolVar(f"is_assigned_faculty_f{f_idx}_to_{sub.subject_id}_s{s}")
                model.Add(assigned_faculty[(sub.subject_id, s)] == f_idx).OnlyEnforceIf(b)
                model.Add(assigned_faculty[(sub.subject_id, s)] != f_idx).OnlyEnforceIf(b.Not())
                is_assigned_faculty_map[(f_idx, sub.subject_id, s)] = b

    # Room assignment booleans (per SECTION - room is shared across all days)
    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            possible_room_indices = subject_possible_rooms[sub.subject_id]
            for r_idx in possible_room_indices:
                b = model.NewBoolVar(f"is_assigned_room_{sub.subject_id}_s{s}_r{r_idx}")
                model.Add(assigned_room[(sub.subject_id, s)] == r_idx).OnlyEnforceIf(b)
                model.Add(assigned_room[(sub.subject_id, s)] != r_idx).OnlyEnforceIf(b.Not())
                is_assigned_room_map[(r_idx, sub.subject_id, s)] = b

    # Batch full-section assignment booleans (batch fully assigned to a section)
    for b_idx, batch in enumerate(batches):
        for sub in batch.subjects:
            for s in range(sub.ideal_num_sections):
                b = model.NewBoolVar(f"is_assigned_batch_{sub.subject_id}_s{s}_b{b_idx}")
                model.Add(section_assignments[(sub.subject_id, s, b_idx)] == batch.population).OnlyEnforceIf(b)
                model.Add(section_assignments[(sub.subject_id, s, b_idx)] != batch.population).OnlyEnforceIf(b.Not())
                is_assigned_batch_map[(b_idx, sub.subject_id, s)] = b

    # Activation booleans (entity assigned AND meeting active)
    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            for d_idx in range(len(config["SCHEDULING_DAYS"])):
                meeting = meetings[(sub.subject_id, s, d_idx)]
                is_active_var = meeting["is_active"]
                
                # Faculty activation booleans
                for f_idx in subject_qualified_faculty[sub.subject_id]:
                    is_assigned_faculty = is_assigned_faculty_map[(f_idx, sub.subject_id, s)]
                    b = model.NewBoolVar(f"active_for_faculty_f{f_idx}_{sub.subject_id}_s{s}_d{d_idx}")
                    model.AddBoolAnd([is_assigned_faculty, is_active_var]).OnlyEnforceIf(b)
                    model.AddBoolOr([is_assigned_faculty.Not(), is_active_var.Not()]).OnlyEnforceIf(b.Not())
                    active_for_faculty_map[(f_idx, sub.subject_id, s, d_idx)] = b
                
                # Room activation booleans (room is per section, not per day)
                for r_idx in subject_possible_rooms[sub.subject_id]:
                    if (r_idx, sub.subject_id, s) not in is_assigned_room_map:
                        continue
                    is_assigned_room = is_assigned_room_map[(r_idx, sub.subject_id, s)]
                    b = model.NewBoolVar(f"active_for_room_r{r_idx}_{sub.subject_id}_s{s}_d{d_idx}")
                    model.AddBoolAnd([is_assigned_room, is_active_var]).OnlyEnforceIf(b)
                    model.AddBoolOr([is_assigned_room.Not(), is_active_var.Not()]).OnlyEnforceIf(b.Not())
                    active_for_room_map[(r_idx, sub.subject_id, s, d_idx)] = b
                
                # Batch activation booleans
                for b_idx, batch in enumerate(batches):
                    if sub in batch.subjects:
                        is_assigned_batch = is_assigned_batch_map[(b_idx, sub.subject_id, s)]
                        b_var = model.NewBoolVar(f"active_for_batch_b{b_idx}_{sub.subject_id}_s{s}_d{d_idx}")
                        model.AddBoolAnd([is_assigned_batch, is_active_var]).OnlyEnforceIf(b_var)
                        model.AddBoolOr([is_assigned_batch.Not(), is_active_var.Not()]).OnlyEnforceIf(b_var.Not())
                        active_for_batch_map[(b_idx, sub.subject_id, s, d_idx)] = b_var

#================================== END OF REUSABLE ASSIGNMENT STORAGE ==================================

#================================== START OF DAY GAP TRACKING [TRACKING/REIFICATION] ==================================
    # Track idle days that fall between teaching days using meeting is_active variables
    
    # Initialize day gap trackers
    faculty_day_gaps = collections.defaultdict(list)
    batch_day_gaps = collections.defaultdict(list)
    
    num_days = len(config["SCHEDULING_DAYS"])
    
    # For each faculty
    for f_idx, fac in enumerate(faculty):
        # Step 1: Collect all active_for_faculty booleans for this faculty, grouped by day
        faculty_active_on_day = {d: [] for d in range(num_days)}
        for (key_f_idx, sub_id, s, d_idx), active_bool in active_for_faculty_map.items():
            if key_f_idx == f_idx:
                faculty_active_on_day[d_idx].append(active_bool)
        
        # Step 2: Create has_class[d] ONCE per day (5 booleans instead of many redundant MaxEquality calls)
        has_class = []
        for day_idx in range(num_days):
            hc = model.NewBoolVar(f"has_class_f{f_idx}_d{day_idx}")
            if faculty_active_on_day[day_idx]:
                model.AddMaxEquality(hc, faculty_active_on_day[day_idx])
            else:
                model.Add(hc == 0)
            has_class.append(hc)
        
        # Step 3: Compute day gaps using ONLY has_class[d] (small input lists for before/after)
        for day_idx in range(1, num_days - 1):
            # has_class_before = OR(has_class[0], ..., has_class[day_idx-1])
            has_before = model.NewBoolVar(f"has_before_f{f_idx}_d{day_idx}")
            model.AddMaxEquality(has_before, has_class[:day_idx])
            
            # has_class_after = OR(has_class[day_idx+1], ..., has_class[num_days-1])
            has_after = model.NewBoolVar(f"has_after_f{f_idx}_d{day_idx}")
            model.AddMaxEquality(has_after, has_class[day_idx+1:])
            
            # is_day_gap = NOT has_class[day_idx] AND has_before AND has_after
            is_day_gap = model.NewBoolVar(f"day_gap_f{f_idx}_d{day_idx}")
            model.AddBoolAnd([has_class[day_idx].Not(), has_before, has_after]).OnlyEnforceIf(is_day_gap)
            model.AddBoolOr([has_class[day_idx], has_before.Not(), has_after.Not()]).OnlyEnforceIf(is_day_gap.Not())
            
            faculty_day_gaps[f_idx].append(is_day_gap)
    
    # Same optimized logic for batches
    for b_idx, batch in enumerate(batches):
        # Step 1: Collect all active_for_batch booleans for this batch, grouped by day
        batch_active_on_day = {d: [] for d in range(num_days)}
        for (key_b_idx, sub_id, s, d_idx), active_bool in active_for_batch_map.items():
            if key_b_idx == b_idx:
                batch_active_on_day[d_idx].append(active_bool)
        
        # Step 2: Create has_class[d] ONCE per day
        has_class = []
        for day_idx in range(num_days):
            hc = model.NewBoolVar(f"has_class_b{b_idx}_d{day_idx}")
            if batch_active_on_day[day_idx]:
                model.AddMaxEquality(hc, batch_active_on_day[day_idx])
            else:
                model.Add(hc == 0)
            has_class.append(hc)
        
        # Step 3: Compute day gaps using ONLY has_class[d]
        for day_idx in range(1, num_days - 1):
            # has_class_before = OR(has_class[0], ..., has_class[day_idx-1])
            has_before = model.NewBoolVar(f"has_before_b{b_idx}_d{day_idx}")
            model.AddMaxEquality(has_before, has_class[:day_idx])
            
            # has_class_after = OR(has_class[day_idx+1], ..., has_class[num_days-1])
            has_after = model.NewBoolVar(f"has_after_b{b_idx}_d{day_idx}")
            model.AddMaxEquality(has_after, has_class[day_idx+1:])
            
            # is_day_gap = NOT has_class[day_idx] AND has_before AND has_after
            is_day_gap = model.NewBoolVar(f"day_gap_b{b_idx}_d{day_idx}")
            model.AddBoolAnd([has_class[day_idx].Not(), has_before, has_after]).OnlyEnforceIf(is_day_gap)
            model.AddBoolOr([has_class[day_idx], has_before.Not(), has_after.Not()]).OnlyEnforceIf(is_day_gap.Not())
            
            batch_day_gaps[b_idx].append(is_day_gap)

#================================== END OF DAY GAP TRACKING ==================================

#================================== START OF GHOST BLOCKS - VARIABLE CREATION ==================================
    """
    Ghost Blocks: Fixed-position vacancy intervals that classes must "kill" to exist.
    
    For every Faculty/Batch on every Day:
        - Physical Grid (GhostBlock): Fixed intervals representing VACANCY
        - Logical Grid (TimeSlots): Boolean (1 = Matter/Class, 0 = Void/Empty)
        - Control: GhostActive[i] (Boolean) - True = Void exists, False = Class killed ghost
        - Inverter Sync: TimeSlots[i] = NOT(GhostActive[i])
    """
    
    # Helper function to calculate slots per day
    def calculate_slots_for_day(day_idx, config):
        """Calculate number of TIME_GRANULARITY slots for a given day"""
        day_start = config["DAY_START_MINUTES"]
        day_end = config["FRIDAY_END_MINUTES"] if day_idx == FRIDAY_IDX else config["DAY_END_MINUTES"]
        day_span = day_end - day_start
        return day_span // TIME_GRANULARITY
    
    # Storage for ghost grids
    faculty_ghost_grid = {}  # (f_idx, day_idx) -> list of GhostSlot dicts
    batch_ghost_grid = {}    # (b_idx, day_idx) -> list of GhostSlot dicts
    
    # Create Ghost Blocks for each Faculty
    for f_idx, fac in enumerate(faculty):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            num_slots = calculate_slots_for_day(day_idx, config)
            day_offset = day_idx * MINUTES_IN_A_DAY
            day_start_abs = config["DAY_START_MINUTES"] + day_offset
            
            ghost_slots = []
            
            for slot_idx in range(num_slots):
                # --- THE PHYSICAL GRID (GhostBlock) ---
                # Fixed position interval representing VACANCY
                ghost_start = day_start_abs + (slot_idx * TIME_GRANULARITY)
                ghost_size = TIME_GRANULARITY  # Fixed size (10 or 30 min)
                ghost_end = ghost_start + ghost_size
                
                # Control: GhostActive[i] (Boolean)
                # True = Void (vacancy exists), False = Matter (class killed this ghost)
                ghost_active = model.NewBoolVar(
                    f"ghost_active_f{f_idx}_d{day_idx}_s{slot_idx}"
                )
                
                # Create optional interval controlled by ghost_active
                # Only "exists" when active (representing vacancy)
                ghost_interval = model.NewOptionalIntervalVar(
                    start=ghost_start,           # Fixed position
                    size=ghost_size,             # Fixed size
                    end=ghost_end,               # Fixed end
                    is_present=ghost_active,     # Only present if vacancy exists
                    name=f"ghost_interval_f{f_idx}_d{day_idx}_s{slot_idx}"
                )
                
                # --- THE LOGICAL GRID (TimeSlots) ---
                # TimeSlots[i] = Matter (1) or Void (0)
                # Inverter: TimeSlots[i] = NOT(GhostActive[i])
                time_slot = model.NewBoolVar(f"timeslot_f{f_idx}_d{day_idx}_s{slot_idx}")
                model.Add(time_slot == 1).OnlyEnforceIf(ghost_active.Not())  # Ghost killed → Matter
                model.Add(time_slot == 0).OnlyEnforceIf(ghost_active)        # Ghost alive → Void
                
                ghost_slots.append({
                    "slot_idx": slot_idx,
                    "ghost_active": ghost_active,      # Control boolean
                    "ghost_interval": ghost_interval,  # Physical representation
                    "time_slot": time_slot,            # Logical representation
                    "start_abs": ghost_start,          # For debugging
                    "end_abs": ghost_end
                })
            
            faculty_ghost_grid[(f_idx, day_idx)] = ghost_slots
    
    # Create Ghost Blocks for each Batch (identical structure)
    for b_idx, batch in enumerate(batches):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            num_slots = calculate_slots_for_day(day_idx, config)
            day_offset = day_idx * MINUTES_IN_A_DAY
            day_start_abs = config["DAY_START_MINUTES"] + day_offset
            
            ghost_slots = []
            
            for slot_idx in range(num_slots):
                ghost_start = day_start_abs + (slot_idx * TIME_GRANULARITY)
                ghost_size = TIME_GRANULARITY
                ghost_end = ghost_start + ghost_size
                
                ghost_active = model.NewBoolVar(
                    f"ghost_active_b{b_idx}_d{day_idx}_s{slot_idx}"
                )
                
                ghost_interval = model.NewOptionalIntervalVar(
                    start=ghost_start,
                    size=ghost_size,
                    end=ghost_end,
                    is_present=ghost_active,
                    name=f"ghost_interval_b{b_idx}_d{day_idx}_s{slot_idx}"
                )
                
                time_slot = model.NewBoolVar(f"timeslot_b{b_idx}_d{day_idx}_s{slot_idx}")
                model.Add(time_slot == 1).OnlyEnforceIf(ghost_active.Not())
                model.Add(time_slot == 0).OnlyEnforceIf(ghost_active)
                
                ghost_slots.append({
                    "slot_idx": slot_idx,
                    "ghost_active": ghost_active,
                    "ghost_interval": ghost_interval,
                    "time_slot": time_slot,
                    "start_abs": ghost_start,
                    "end_abs": ghost_end
                })
            
            batch_ghost_grid[(b_idx, day_idx)] = ghost_slots
    
    # Print Ghost Blocks variable count
    total_faculty_ghost_vars = len(faculty) * len(config["SCHEDULING_DAYS"]) * calculate_slots_for_day(0, config) * 3
    total_batch_ghost_vars = len(batches) * len(config["SCHEDULING_DAYS"]) * calculate_slots_for_day(0, config) * 3
    print(f"👻 Ghost Blocks created:")
    print(f"   Faculty: {len(faculty)} × {len(config['SCHEDULING_DAYS'])} days × {calculate_slots_for_day(0, config)} slots × 3 vars = ~{total_faculty_ghost_vars:,} variables")
    print(f"   Batches: {len(batches)} × {len(config['SCHEDULING_DAYS'])} days × {calculate_slots_for_day(0, config)} slots × 3 vars = ~{total_batch_ghost_vars:,} variables")
    print(f"   Total Ghost variables: ~{total_faculty_ghost_vars + total_batch_ghost_vars:,}")

#================================== END OF GHOST BLOCKS - VARIABLE CREATION ==================================

#================================== START OF LOGICAL ENGINE - STREAK ANALYSIS ==================================
    """
    Logical Engine: Track consecutive class and gap streaks
    - ActiveStreak[i]: Number of consecutive CLASS slots ending at position i
    - VacantStreak[i]: Number of consecutive GAP slots ending at position i
    
    Uses time_slot boolean (1 = CLASS, 0 = GAP) from Ghost Blocks
    """
    
    print("[Ghost Blocks] Building Logical Engine - Streak Analysis...")
    
    # Storage for streak variables
    faculty_active_streak = {}  # (f_idx, day_idx) -> list of IntVars
    faculty_vacant_streak = {}  # (f_idx, day_idx) -> list of IntVars
    batch_active_streak = {}    # (b_idx, day_idx) -> list of IntVars
    batch_vacant_streak = {}    # (b_idx, day_idx) -> list of IntVars
    
    # Faculty Streak Tracking
    for f_idx in range(len(faculty)):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            ghost_slots = faculty_ghost_grid[(f_idx, day_idx)]
            N = len(ghost_slots)
            
            faculty_active_streak[(f_idx, day_idx)] = []
            faculty_vacant_streak[(f_idx, day_idx)] = []
            
            for i in range(N):
                time_slot = ghost_slots[i]["time_slot"]  # 1 = CLASS, 0 = GAP
                
                # ActiveStreak[i]: Consecutive CLASS slots ending at i
                active_streak = model.NewIntVar(0, N, f"active_streak_f{f_idx}_d{day_idx}_s{i}")
                
                if i == 0:
                    # First slot: ActiveStreak[0] = 1 if CLASS, else 0
                    model.Add(active_streak == 1).OnlyEnforceIf(time_slot)
                    model.Add(active_streak == 0).OnlyEnforceIf(time_slot.Not())
                else:
                    prev_active = faculty_active_streak[(f_idx, day_idx)][i-1]
                    
                    # If GAP: ActiveStreak[i] = 0
                    model.Add(active_streak == 0).OnlyEnforceIf(time_slot.Not())
                    
                    # If CLASS: ActiveStreak[i] = ActiveStreak[i-1] + 1
                    model.Add(active_streak == prev_active + 1).OnlyEnforceIf(time_slot)
                
                faculty_active_streak[(f_idx, day_idx)].append(active_streak)
                
                # VacantStreak[i]: Consecutive GAP slots ending at i
                vacant_streak = model.NewIntVar(0, N, f"vacant_streak_f{f_idx}_d{day_idx}_s{i}")
                
                if i == 0:
                    # First slot: VacantStreak[0] = 1 if GAP, else 0
                    model.Add(vacant_streak == 1).OnlyEnforceIf(time_slot.Not())
                    model.Add(vacant_streak == 0).OnlyEnforceIf(time_slot)
                else:
                    prev_vacant = faculty_vacant_streak[(f_idx, day_idx)][i-1]
                    
                    # If CLASS: VacantStreak[i] = 0
                    model.Add(vacant_streak == 0).OnlyEnforceIf(time_slot)
                    
                    # If GAP: VacantStreak[i] = VacantStreak[i-1] + 1
                    model.Add(vacant_streak == prev_vacant + 1).OnlyEnforceIf(time_slot.Not())
                
                faculty_vacant_streak[(f_idx, day_idx)].append(vacant_streak)
    
    # Batch Streak Tracking
    for b_idx in range(len(batches)):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            ghost_slots = batch_ghost_grid[(b_idx, day_idx)]
            N = len(ghost_slots)
            
            batch_active_streak[(b_idx, day_idx)] = []
            batch_vacant_streak[(b_idx, day_idx)] = []
            
            for i in range(N):
                time_slot = ghost_slots[i]["time_slot"]
                
                # ActiveStreak[i]
                active_streak = model.NewIntVar(0, N, f"active_streak_b{b_idx}_d{day_idx}_s{i}")
                
                if i == 0:
                    model.Add(active_streak == 1).OnlyEnforceIf(time_slot)
                    model.Add(active_streak == 0).OnlyEnforceIf(time_slot.Not())
                else:
                    prev_active = batch_active_streak[(b_idx, day_idx)][i-1]
                    model.Add(active_streak == 0).OnlyEnforceIf(time_slot.Not())
                    model.Add(active_streak == prev_active + 1).OnlyEnforceIf(time_slot)
                
                batch_active_streak[(b_idx, day_idx)].append(active_streak)
                
                # VacantStreak[i]
                vacant_streak = model.NewIntVar(0, N, f"vacant_streak_b{b_idx}_d{day_idx}_s{i}")
                
                if i == 0:
                    model.Add(vacant_streak == 1).OnlyEnforceIf(time_slot.Not())
                    model.Add(vacant_streak == 0).OnlyEnforceIf(time_slot)
                else:
                    prev_vacant = batch_vacant_streak[(b_idx, day_idx)][i-1]
                    model.Add(vacant_streak == 0).OnlyEnforceIf(time_slot)
                    model.Add(vacant_streak == prev_vacant + 1).OnlyEnforceIf(time_slot.Not())
                
                batch_vacant_streak[(b_idx, day_idx)].append(vacant_streak)
    
    total_streak_vars = (len(faculty) + len(batches)) * len(config["SCHEDULING_DAYS"]) * 2
    avg_slots_per_day = len(faculty_ghost_grid[(0, 0)])
    total_intvars = (len(faculty) + len(batches)) * len(config["SCHEDULING_DAYS"]) * avg_slots_per_day * 2
    print(f"   Created streak tracking for {total_streak_vars} entity-day combinations")
    print(f"   Total streak IntVars: ~{total_intvars:,} (ActiveStreak + VacantStreak per slot)")

#================================== END OF LOGICAL ENGINE - STREAK ANALYSIS ==================================

#================================== START OF LOGICAL ENGINE - HARD CONSTRAINTS ==================================
    print("\n5. Adding Logical Engine Hard Constraints (Max Class, Min Gap)...")
    
    # Calculate slot limits from config
    MAX_CLASS_SLOTS = int((config["MAX_CONTINUOUS_CLASS_HOURS"] * 60) / config["TIME_GRANULARITY_MINUTES"])
    MIN_GAP_SLOTS = int((config["MIN_GAP_HOURS"] * 60) / config["TIME_GRANULARITY_MINUTES"])
    
    print(f"   Max continuous class: {config['MAX_CONTINUOUS_CLASS_HOURS']}h = {MAX_CLASS_SLOTS} slots")
    print(f"   Min gap: {config['MIN_GAP_HOURS']}h = {MIN_GAP_SLOTS} slots")
    
    total_max_class_constraints = 0
    total_min_gap_constraints = 0
    
    # Faculty constraints
    for f_idx, faculty_member in enumerate(faculty):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = faculty_ghost_grid[(f_idx, day_idx)]
            N = len(slots)
            
            for i in range(N):
                time_slot = slots[i]["time_slot"]
                active_streak = faculty_active_streak[(f_idx, day_idx)][i]
                vacant_streak = faculty_vacant_streak[(f_idx, day_idx)][i]
                
                # HARD: Max Continuous Class - ActiveStreak[i] <= MAX_CLASS_SLOTS
                model.Add(active_streak <= MAX_CLASS_SLOTS)
                total_max_class_constraints += 1
                
                # HARD: Min Gap - VacantStreak[i] >= MIN_GAP_SLOTS when gap ends
                # GapEndsHere = (TimeSlots[i] == 0) AND (i < N-1 AND TimeSlots[i+1] == 1) AND (VacantStreak[i] <= i)
                if i < N - 1:
                    next_time_slot = slots[i+1]["time_slot"]
                    gap_ends_here = model.NewBoolVar(f"gap_ends_f{f_idx}_d{day_idx}_i{i}")
                    
                    # gap_ends_here = (time_slot == 0) AND (next_time_slot == 1) AND (vacant_streak <= i)
                    model.AddBoolAnd([time_slot.Not(), next_time_slot]).OnlyEnforceIf(gap_ends_here)
                    model.AddBoolOr([time_slot, next_time_slot.Not()]).OnlyEnforceIf(gap_ends_here.Not())
                    
                    # If gap_ends_here, then vacant_streak >= MIN_GAP_SLOTS
                    model.Add(vacant_streak >= MIN_GAP_SLOTS).OnlyEnforceIf(gap_ends_here)
                    total_min_gap_constraints += 1
    
    # Batch constraints
    for b_idx, batch in enumerate(batches):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = batch_ghost_grid[(b_idx, day_idx)]
            N = len(slots)
            
            for i in range(N):
                time_slot = slots[i]["time_slot"]
                active_streak = batch_active_streak[(b_idx, day_idx)][i]
                vacant_streak = batch_vacant_streak[(b_idx, day_idx)][i]
                
                # HARD: Max Continuous Class - ActiveStreak[i] <= MAX_CLASS_SLOTS
                model.Add(active_streak <= MAX_CLASS_SLOTS)
                total_max_class_constraints += 1
                
                # HARD: Min Gap - VacantStreak[i] >= MIN_GAP_SLOTS when gap ends
                if i < N - 1:
                    next_time_slot = slots[i+1]["time_slot"]
                    gap_ends_here = model.NewBoolVar(f"gap_ends_b{b_idx}_d{day_idx}_i{i}")
                    
                    # gap_ends_here = (time_slot == 0) AND (next_time_slot == 1)
                    model.AddBoolAnd([time_slot.Not(), next_time_slot]).OnlyEnforceIf(gap_ends_here)
                    model.AddBoolOr([time_slot, next_time_slot.Not()]).OnlyEnforceIf(gap_ends_here.Not())
                    
                    # If gap_ends_here, then vacant_streak >= MIN_GAP_SLOTS
                    model.Add(vacant_streak >= MIN_GAP_SLOTS).OnlyEnforceIf(gap_ends_here)
                    total_min_gap_constraints += 1
    
    print(f"   Max Continuous Class constraints: {total_max_class_constraints}")
    print(f"   Min Gap constraints: {total_min_gap_constraints}")

#================================== END OF LOGICAL ENGINE - HARD CONSTRAINTS ==================================

#================================== START OF VIOLATION TRACKERS [VARIABLES] ==================================
    faculty_overload_minutes = [model.NewIntVar(0, 10000, f"overload_mins_f{f_idx}") for f_idx, f in enumerate(faculty)]
    faculty_underfill_minutes = [model.NewIntVar(0, 10000, f"underfill_mins_f{f_idx}") for f_idx, f in enumerate(faculty)]
    room_overcapacity_students = { (sub.subject_id, s): model.NewIntVar(0, (sub.max_enrollment or 40) * 2, f"room_over_{sub.subject_id}_s{s}") for sub in subjects for s in range(sub.ideal_num_sections) }
    section_overfill_students = { (sub.subject_id, s): model.NewIntVar(0, (sub.max_enrollment or 40) * 2, f"sec_over_{sub.subject_id}_s{s}") for sub in subjects for s in range(sub.ideal_num_sections) }
    
    # Underfill tracking for all subjects (hardcoded minimum of 20 students)
    MIN_SECTION_STUDENTS = 20
    section_underfill_students = { (sub.subject_id, s): model.NewIntVar(0, MIN_SECTION_STUDENTS, f"sec_under_{sub.subject_id}_s{s}") for sub in subjects for s in range(sub.ideal_num_sections) }
    
    # Violation trackers for Logical Engine soft constraints
    faculty_under_minimum_block = collections.defaultdict(lambda: collections.defaultdict(list))
    batch_under_minimum_block = collections.defaultdict(lambda: collections.defaultdict(list))
    faculty_excess_gaps = collections.defaultdict(lambda: collections.defaultdict(list))
    batch_excess_gaps = collections.defaultdict(lambda: collections.defaultdict(list))
    
    # Tracking for non-preferred subject assignments (soft constraint)
    faculty_non_preferred_subject = collections.defaultdict(lambda: collections.defaultdict(list))
#================================== END OF VIOLATION TRACKERS ==================================

#================================== START OF BATCH SECTION ASSIGNMENT [HARD/REIFICATION] ==================================
    # [HARD] A batch can't be split across sections - must go to exactly one
    section_batch_picks = collections.defaultdict(list)  # key: (sub_id, s) -> list of y_s Bools
    
    for b_idx, batch in enumerate(batches):
        for sub in batch.subjects:
            batch_population_across_sections = []
            chosen_full = []
            for s in range(sub.ideal_num_sections):
                pop_s = model.NewIntVar(0, batch.population, f"subject_section_batch_population_{sub.subject_id}_s{s}_b{b_idx}")
                model.Add(pop_s == section_assignments[(sub.subject_id, s, b_idx)])
                y_s = model.NewBoolVar(f"full_batch_pick_{sub.subject_id}_s{s}_b{b_idx}")
                # y_s ↔ (pop_s == batch.population)
                model.Add(pop_s == batch.population).OnlyEnforceIf(y_s)
                model.Add(pop_s != batch.population).OnlyEnforceIf(y_s.Not())
                # If not chosen, force zero (prevents partials)
                model.Add(pop_s == 0).OnlyEnforceIf(y_s.Not())
                batch_population_across_sections.append(pop_s)
                chosen_full.append(y_s)
                
                # Collect for section_has_batch detection
                section_batch_picks[(sub.subject_id, s)].append(y_s)

            # Exactly one section receives the full batch
            model.Add(sum(chosen_full) == 1)
#================================== END OF BATCH SECTION ASSIGNMENT ==================================
    
#================================== START OF SECTION HAS BATCH DETECTION [TRACKING] ==================================
    # Create section_has_batch[(sub_id, s)] = True iff at least one batch chose this section
    section_has_batch = {}
    
    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            key = (sub.subject_id, s)
            has_batch = model.NewBoolVar(f"section_has_batch_{sub.subject_id}_s{s}")
            
            if key in section_batch_picks and section_batch_picks[key]:
                # At least one batch could pick this section
                # has_batch = OR(all y_s for this section)
                model.AddMaxEquality(has_batch, section_batch_picks[key])
            else:
                # No batch can pick this section (shouldn't happen, but handle gracefully)
                model.Add(has_batch == 0)
            
            section_has_batch[key] = has_batch
#================================== END OF SECTION HAS BATCH DETECTION ==================================
    
#================================== START OF SYMMETRY BREAKING [HARD] ==================================
    # Break symmetry between identical sections of the same subject:
    # - Pack used sections to the front (so we don't permute "used" vs "unused" sections)
    # - Impose nondecreasing ordering on assigned faculty/room across sections
    """ for sub in subjects:
        for s in range(sub.ideal_num_sections - 1):
            key_a = (sub.subject_id, s)
            key_b = (sub.subject_id, s + 1)

            # Pack used sections first: has_batch[s] >= has_batch[s+1]
            model.Add(section_has_batch[key_a] >= section_has_batch[key_b])

            # Canonicalize assignment ordering among sections
            # (Dummy indices are max, so they naturally drift to the end)
            model.Add(assigned_faculty[key_a] <= assigned_faculty[key_b])
            model.Add(assigned_room[key_a] <= assigned_room[key_b]) """
#================================== END OF SYMMETRY BREAKING ==================================
    
#================================== START OF GATED DUMMY VIOLATIONS [GATING] ==================================
    # Gate dummy violations by section_has_batch - only count as violations when section has students
    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            key = (sub.subject_id, s)
            has_batch = section_has_batch[key]
            
            # Gate is_dummy_faculty: only counts when section has students
            raw_dummy_fac = is_dummy_faculty[key]
            actual_dummy_faculty = model.NewBoolVar(f"actual_dummy_faculty_{sub.subject_id}_s{s}")
            model.AddBoolAnd([has_batch, raw_dummy_fac]).OnlyEnforceIf(actual_dummy_faculty)
            model.AddBoolOr([has_batch.Not(), raw_dummy_fac.Not()]).OnlyEnforceIf(actual_dummy_faculty.Not())
            is_dummy_faculty[key] = actual_dummy_faculty
            
            # Gate is_dummy_room: only counts when section has students (room is per section now)
            raw_dummy_rm = is_dummy_room[key]
            actual_dummy_room = model.NewBoolVar(f"actual_dummy_room_{sub.subject_id}_s{s}")
            model.AddBoolAnd([has_batch, raw_dummy_rm]).OnlyEnforceIf(actual_dummy_room)
            model.AddBoolOr([has_batch.Not(), raw_dummy_rm.Not()]).OnlyEnforceIf(actual_dummy_room.Not())
            is_dummy_room[key] = actual_dummy_room
#================================== END OF GATED DUMMY VIOLATIONS ==================================
    
#================================== START OF FORCE UNUSED SECTION RESOURCES [HARD] ==================================
    # When section_has_batch is False, force dummy faculty/room and inactive meetings
    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            key = (sub.subject_id, s)
            has_batch = section_has_batch[key]
            
            # Force dummy faculty when unused
            model.Add(assigned_faculty[key] == DUMMY_FACULTY_IDX).OnlyEnforceIf(has_batch.Not())
            
            # Force dummy room when unused (room is per section now)
            model.Add(assigned_room[key] == DUMMY_ROOM_IDX).OnlyEnforceIf(has_batch.Not())
            
            # Force inactive meetings for each day
            for d_idx in range(len(config["SCHEDULING_DAYS"])):
                meeting_key = (sub.subject_id, s, d_idx)
                model.Add(meetings[meeting_key]["is_active"] == 0).OnlyEnforceIf(has_batch.Not())
#================================== END OF FORCE UNUSED SECTION RESOURCES ==================================

#================================== START OF NO-OVERLAP CONSTRAINTS + GHOST COLLISION [HARD] ==================================
    """
    Physics Engine Rule 1: COLLISION (NoOverlap)
    - Classes physically push ghosts out of the way
    - When a class occupies a time slot, ghost intervals in that period MUST deactivate
    - NoOverlap enforces: Classes + Ghosts cannot coexist in the same space
    """
    
    #--- ROOM NO-OVERLAP (No Ghost Blocks - Rooms don't have vacancy tracking) ---
    for r_idx, _ in enumerate(rooms):
        intervals_in_room = []
        for sub in subjects:
            for s in range(sub.ideal_num_sections):
                for d_idx in range(len(config["SCHEDULING_DAYS"])):
                    key_assign = (r_idx, sub.subject_id, s, d_idx)
                    
                    # Check if this room has an activation boolean for this meeting
                    if key_assign not in active_for_room_map:
                        # Either room not compatible or meeting inactive
                        continue
                    
                    # Presence literal: active_for_room = (assigned_room == r_idx) AND meeting is active
                    active_for_room = active_for_room_map[key_assign]

                    # Get canonical meeting variables directly (not from optional interval)
                    mtg = meetings[(sub.subject_id, s, d_idx)]
                    start_var = mtg["start"]
                    duration_var = mtg["duration"]
                    end_var = mtg["end"]

                    # Optional interval directly from canonical IntVars
                    room_interval = model.NewOptionalIntervalVar(
                        start_var,
                        duration_var,
                        end_var,
                        active_for_room,
                        f"room_int_r{r_idx}_{sub.subject_id}_s{s}_d{d_idx}"
                    )
                    intervals_in_room.append(room_interval)

        if intervals_in_room:
            model.AddNoOverlap(intervals_in_room)

    #--- FACULTY NO-OVERLAP + GHOST COLLISION ---
    for f_idx, f in enumerate(faculty):
        faculty_intervals = intervals_per_faculty[f_idx][:]  # Start with any existing intervals
        qualified_subjects = faculty_qualified_subjects.get(f_idx, [])
        
        # Collect class intervals
        for sub in qualified_subjects:
            for s in range(sub.ideal_num_sections):
                # Check if this faculty has an assignment boolean for this section
                if (f_idx, sub.subject_id, s) not in is_assigned_faculty_map:
                    continue

                for d_idx in range(len(config["SCHEDULING_DAYS"])):
                    # Check if this faculty has an activation boolean for this meeting
                    if (f_idx, sub.subject_id, s, d_idx) not in active_for_faculty_map:
                        continue
                    
                    # Reuse: is this meeting active for this faculty?
                    active_for_faculty = active_for_faculty_map[(f_idx, sub.subject_id, s, d_idx)]
                    mtg = meetings[(sub.subject_id, s, d_idx)]
                    
                    # Optional interval directly from canonical IntVars
                    faculty_interval = model.NewOptionalIntervalVar(
                        mtg["start"], mtg["duration"], mtg["end"],
                        active_for_faculty,
                        f"faculty_int_f{f_idx}_{sub.subject_id}_s{s}_d{d_idx}"
                    )
                    faculty_intervals.append(faculty_interval)
        
        # ⚡ GHOST COLLISION: Add ghost intervals for each day
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            ghost_slots = faculty_ghost_grid[(f_idx, day_idx)]
            for ghost_slot in ghost_slots:
                faculty_intervals.append(ghost_slot["ghost_interval"])

        # Physics: Classes + Ghosts cannot overlap
        if faculty_intervals:
            model.AddNoOverlap(faculty_intervals)

    #--- BATCH NO-OVERLAP + GHOST COLLISION + EXTERNAL MEETINGS ---
    MINUTES_IN_A_DAY = 1440
    FRIDAY_IDX = 4  # Friday index

    # External meetings (fixed intervals for batches)
    for b_idx, batch in enumerate(batches):
        for meeting in batch.external_meetings:
            day_offset = meeting.day_index * MINUTES_IN_A_DAY
            
            # Trim external meetings to fit within day boundaries
            day_idx = meeting.day_index
            day_start = config["DAY_START_MINUTES"]
            day_end = config["FRIDAY_END_MINUTES"] if day_idx == FRIDAY_IDX else config["DAY_END_MINUTES"]
            
            # Calculate absolute time bounds
            day_start_abs = day_start + day_offset
            day_end_abs = day_end + day_offset
            
            # Original external meeting times
            start_abs_min = meeting.start_minutes + day_offset
            end_abs_min = meeting.end_minutes + day_offset
            
            # Clamp to day boundaries
            start_abs_min = max(start_abs_min, day_start_abs)
            end_abs_min = min(end_abs_min, day_end_abs)
            
            duration = end_abs_min - start_abs_min
            
            if duration <= 0: continue
                
            external_interval = model.NewFixedSizeIntervalVar(
                start_abs_min,
                duration,
                f"external_interval_b{b_idx}_d{meeting.day_index}_m{meeting.start_minutes}"
            )
            intervals_per_batch[b_idx].append(external_interval)

    # Batch no-overlap with ghost collision
    for b_idx, batch in enumerate(batches):
        batch_intervals = intervals_per_batch[b_idx][:]  # includes external fixed intervals
        
        # Collect class intervals
        for sub in batch.subjects:
            for s in range(sub.ideal_num_sections):
                # Check if this batch has an assignment boolean for this section
                if (b_idx, sub.subject_id, s) not in is_assigned_batch_map:
                    continue
                
                for d_idx in range(len(config["SCHEDULING_DAYS"])):
                    # Check if this batch has an activation boolean for this meeting
                    if (b_idx, sub.subject_id, s, d_idx) not in active_for_batch_map:
                        continue

                    # Reuse: is this meeting active for this batch?
                    active_for_batch = active_for_batch_map[(b_idx, sub.subject_id, s, d_idx)]
                    mtg = meetings[(sub.subject_id, s, d_idx)]
                    
                    # Optional interval directly from canonical IntVars
                    batch_interval = model.NewOptionalIntervalVar(
                        mtg["start"], mtg["duration"], mtg["end"],
                        active_for_batch,
                        f"batch_int_b{b_idx}_{sub.subject_id}_s{s}_d{d_idx}"
                    )
                    batch_intervals.append(batch_interval)
        
        # ⚡ GHOST COLLISION: Add ghost intervals for each day
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            ghost_slots = batch_ghost_grid[(b_idx, day_idx)]
            for ghost_slot in ghost_slots:
                batch_intervals.append(ghost_slot["ghost_interval"])
        
        # Physics: Classes + Ghosts + External cannot overlap
        if batch_intervals:
            model.AddNoOverlap(batch_intervals)
#================================== END OF NO-OVERLAP CONSTRAINTS + GHOST COLLISION ==================================

#================================== START OF CONSERVATION OF TIME [HARD] ==================================
    """
    Physics Engine Rule 2: CONSERVATION OF TIME (Checksum)
    - Time cannot be destroyed, only converted from Void to Matter
    - Total active ghosts + total class time = total available time
    - Prevents solver from "cheating" by turning off ghosts without scheduling classes
    """
    
    # Conservation for Faculty (per day)
    for f_idx, fac in enumerate(faculty):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            ghost_slots = faculty_ghost_grid[(f_idx, day_idx)]
            num_slots = len(ghost_slots)
            
            # Calculate total class minutes for this faculty on this day
            class_minutes_terms = []
            qualified_subjects = faculty_qualified_subjects.get(f_idx, [])
            
            for sub in qualified_subjects:
                for s in range(sub.ideal_num_sections):
                    # Check if faculty is assigned to this section
                    if (f_idx, sub.subject_id, s) not in is_assigned_faculty_map:
                        continue
                    
                    # Check if this meeting is active for this faculty
                    key = (f_idx, sub.subject_id, s, day_idx)
                    if key not in active_for_faculty_map:
                        continue
                    
                    active_for_faculty = active_for_faculty_map[key]
                    duration_var = meetings[(sub.subject_id, s, day_idx)]["duration"]
                    
                    # active_minutes = duration * active_for_faculty (boolean multiplication)
                    max_dur = duration_var.Proto().domain[-1]
                    active_minutes = model.NewIntVar(0, max_dur, 
                        f"class_mins_f{f_idx}_d{day_idx}_{sub.subject_id}_s{s}")
                    model.AddMultiplicationEquality(active_minutes, [duration_var, active_for_faculty])
                    class_minutes_terms.append(active_minutes)
            
            total_class_minutes = sum(class_minutes_terms) if class_minutes_terms else 0
            
            # Calculate total ghost minutes (vacancy)
            total_ghost_slots = sum(ghost_slot["ghost_active"] for ghost_slot in ghost_slots)
            total_ghost_minutes = total_ghost_slots * TIME_GRANULARITY
            
            # Conservation Law: Ghost Minutes + Class Minutes = Total Available Time
            total_available_minutes = num_slots * TIME_GRANULARITY
            
            model.Add(total_ghost_minutes + total_class_minutes == total_available_minutes)
    
    # Conservation for Batches (per day)
    for b_idx, batch in enumerate(batches):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            ghost_slots = batch_ghost_grid[(b_idx, day_idx)]
            num_slots = len(ghost_slots)
            
            # Calculate total class minutes for this batch on this day
            class_minutes_terms = []
            
            # 1. Regular class meetings
            for sub in batch.subjects:
                for s in range(sub.ideal_num_sections):
                    # Check if batch is assigned to this section
                    if (b_idx, sub.subject_id, s) not in is_assigned_batch_map:
                        continue
                    
                    # Check if this meeting is active for this batch
                    key = (b_idx, sub.subject_id, s, day_idx)
                    if key not in active_for_batch_map:
                        continue
                    
                    active_for_batch = active_for_batch_map[key]
                    duration_var = meetings[(sub.subject_id, s, day_idx)]["duration"]
                    
                    # active_minutes = duration * active_for_batch
                    max_dur = duration_var.Proto().domain[-1]
                    active_minutes = model.NewIntVar(0, max_dur, 
                        f"class_mins_b{b_idx}_d{day_idx}_{sub.subject_id}_s{s}")
                    model.AddMultiplicationEquality(active_minutes, [duration_var, active_for_batch])
                    class_minutes_terms.append(active_minutes)
            
            # 2. External meetings (fixed duration)
            for meeting in batch.external_meetings:
                if meeting.day_index == day_idx:
                    external_duration = meeting.end_minutes - meeting.start_minutes
                    if external_duration > 0:
                        class_minutes_terms.append(external_duration)  # Constant
            
            total_class_minutes = sum(class_minutes_terms) if class_minutes_terms else 0
            
            # Calculate total ghost minutes
            total_ghost_slots = sum(ghost_slot["ghost_active"] for ghost_slot in ghost_slots)
            total_ghost_minutes = total_ghost_slots * TIME_GRANULARITY
            
            # Conservation Law
            total_available_minutes = num_slots * TIME_GRANULARITY
            
            model.Add(total_ghost_minutes + total_class_minutes == total_available_minutes)
    
    print(f"⚡ Physics Engine activated:")
    print(f"   Collision: Ghost intervals added to NoOverlap constraints")
    print(f"   Conservation: {len(faculty) * len(config['SCHEDULING_DAYS']) + len(batches) * len(config['SCHEDULING_DAYS'])} checksum constraints")

#================================== END OF CONSERVATION OF TIME ==================================

#================================== START OF DURATION CONSTRAINT [HARD-RELAXED] ==================================
    # [HARD-RELAXED] Duration constraint with boolean slack - gated by section_has_batch
    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            key = (sub.subject_id, s)
            has_batch = section_has_batch[key]

            # Calculate total duration using AddMultiplicationEquality (boolean multiplier pattern)
            total_duration_terms = []
            for d in range(len(config["SCHEDULING_DAYS"])):
                mtg = meetings[(sub.subject_id, s, d)]
                duration_var = mtg["duration"]
                is_active_var = mtg["is_active"]
                
                # Use native multiplication: active_duration = duration_var * is_active_var
                max_duration = duration_var.Proto().domain[-1]
                active_duration = model.NewIntVar(0, max_duration, f"active_dur_{sub.subject_id}_s{s}_d{d}")
                model.AddMultiplicationEquality(active_duration, [duration_var, is_active_var])
                total_duration_terms.append(active_duration)
            
            total_duration = sum(total_duration_terms)
            
            # Boolean: True if duration requirement is NOT met (when section is active)
            has_duration_violation = model.NewBoolVar(f"duration_violation_{sub.subject_id}_s{s}")
            
            # Duration constraints based on violation flag
            model.Add(total_duration == sub.required_weekly_minutes).OnlyEnforceIf(has_duration_violation.Not())
            model.Add(total_duration < sub.required_weekly_minutes).OnlyEnforceIf(has_duration_violation)
            
            # Actual violation only counts when section has students
            actual_duration_violation = model.NewBoolVar(f"actual_duration_violation_{sub.subject_id}_s{s}")
            model.AddBoolAnd([has_batch, has_duration_violation]).OnlyEnforceIf(actual_duration_violation)
            model.AddBoolOr([has_batch.Not(), has_duration_violation.Not()]).OnlyEnforceIf(actual_duration_violation.Not())
            
            # Count active meetings to determine if section is empty
            active_meeting_flags = [meetings[(sub.subject_id, s, d)]["is_active"] for d in range(len(config["SCHEDULING_DAYS"]))]
            no_meetings = model.NewBoolVar(f"no_meetings_{sub.subject_id}_s{s}")

            # If sum of flags is 0, then no_meetings is True
            model.Add(sum(active_meeting_flags) == 0).OnlyEnforceIf(no_meetings)
            # If sum of flags > 0, then no_meetings is False
            model.Add(sum(active_meeting_flags) > 0).OnlyEnforceIf(no_meetings.Not())

            # Force dummy faculty/room based on active flag count
            model.Add(assigned_faculty[key] == DUMMY_FACULTY_IDX).OnlyEnforceIf(no_meetings)
            model.Add(assigned_room[key] == DUMMY_ROOM_IDX).OnlyEnforceIf(no_meetings)
            
            # MINIMUM DURATION THRESHOLD FOR REAL RESOURCES
            # If assigned real faculty/room, enforce minimum total_duration
            # CHANGE THIS VALUE to adjust threshold:
            #   - Set to 0: No minimum (only prevents zero-duration assignments via has_zero_duration above)
            #   - Set to sub.required_weekly_minutes: Force complete hours for real faculty/room
            #   - Set to any value in between: Partial threshold
            MIN_DURATION_FOR_REAL_FACULTY = 1  # ← CHANGE THIS to set minimum duration
            MIN_DURATION_FOR_REAL_ROOM = 1   # ← CHANGE THIS to set minimum duration
            
            if MIN_DURATION_FOR_REAL_FACULTY > 0:
                # If assigned to real faculty (not dummy), total_duration must meet threshold
                has_real_faculty = model.NewBoolVar(f"has_real_fac_{sub.subject_id}_s{s}")
                model.Add(assigned_faculty[key] != DUMMY_FACULTY_IDX).OnlyEnforceIf(has_real_faculty)
                model.Add(assigned_faculty[key] == DUMMY_FACULTY_IDX).OnlyEnforceIf(has_real_faculty.Not())
                
                # Real faculty → total_duration >= MIN_DURATION_FOR_REAL_FACULTY
                model.Add(total_duration >= MIN_DURATION_FOR_REAL_FACULTY).OnlyEnforceIf(has_real_faculty)
            
            if MIN_DURATION_FOR_REAL_ROOM > 0:
                # If assigned to real room (not dummy), total_duration must meet threshold
                has_real_room = model.NewBoolVar(f"has_real_room_{sub.subject_id}_s{s}")
                model.Add(assigned_room[key] != DUMMY_ROOM_IDX).OnlyEnforceIf(has_real_room)
                model.Add(assigned_room[key] == DUMMY_ROOM_IDX).OnlyEnforceIf(has_real_room.Not())
                
                # Real room → total_duration >= MIN_DURATION_FOR_REAL_ROOM
                model.Add(total_duration >= MIN_DURATION_FOR_REAL_ROOM).OnlyEnforceIf(has_real_room)
            
            duration_violations[key] = actual_duration_violation
#================================== END OF DURATION CONSTRAINT ==================================

#================================== START OF LECTURE-LAB CONSTRAINTS [HARD] ==================================
    # [HARD] All lecture/lab pair meetings have same students
    for sub in subjects:
        if is_lab_subject(sub):
            lec_sub_id = sub.linked_subject_id
            for s in range(sub.ideal_num_sections):
                for b_idx, batch in enumerate(batches):
                    if sub.subject_id in [subject.subject_id for subject in batch.subjects]:
                        model.Add(section_assignments[(sub.subject_id, s, b_idx)] == section_assignments[(lec_sub_id, s, b_idx)])

    # [HARD] Consecutive Lecture then Lab
    for sub in subjects:
        if is_lab_subject(sub):
            lec_sub_id = sub.linked_subject_id
            for s in range(sub.ideal_num_sections):
                for d_idx in range(len(config["SCHEDULING_DAYS"])):
                    lab_meeting = meetings[(sub.subject_id, s, d_idx)]
                    lec_meeting = meetings[(lec_sub_id, s, d_idx)]
                    model.Add(lab_meeting["is_active"] == lec_meeting["is_active"])
                    model.Add(lab_meeting["start"] == lec_meeting["end"]).OnlyEnforceIf(lab_meeting["is_active"])

                    # Lec and lab subjects have same teacher and room
                    model.Add(assigned_faculty[(sub.subject_id, s)] == assigned_faculty[(lec_sub_id, s)])
                    model.Add(assigned_room[(sub.subject_id, s)] == assigned_room[(lec_sub_id, s)])

    # [HARD] Linked subjects must both have active meetings or both have none
    for sub in subjects:
        if is_lab_subject(sub):
            lec_sub_id = sub.linked_subject_id
            for s in range(sub.ideal_num_sections):
                lab_active_meetings = [meetings[(sub.subject_id, s, d)]["is_active"] for d in range(len(config["SCHEDULING_DAYS"]))]
                lab_has_any_active = model.NewBoolVar(f"lab_has_active_{sub.subject_id}_s{s}")
                model.AddBoolOr(lab_active_meetings).OnlyEnforceIf(lab_has_any_active)
                model.AddBoolAnd([m.Not() for m in lab_active_meetings]).OnlyEnforceIf(lab_has_any_active.Not())
                
                lec_active_meetings = [meetings[(lec_sub_id, s, d)]["is_active"] for d in range(len(config["SCHEDULING_DAYS"]))]
                lec_has_any_active = model.NewBoolVar(f"lec_has_active_{lec_sub_id}_s{s}")
                model.AddBoolOr(lec_active_meetings).OnlyEnforceIf(lec_has_any_active)
                model.AddBoolAnd([m.Not() for m in lec_active_meetings]).OnlyEnforceIf(lec_has_any_active.Not())
                
                model.Add(lab_has_any_active == lec_has_any_active)
#================================== END OF LECTURE-LAB CONSTRAINTS ==================================

#================================== START OF MEETING SEPARATION CONSTRAINTS [HARD] ==================================
    # [HARD] Force at least 1 day apart per meeting
    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            for d1 in range(len(config["SCHEDULING_DAYS"])):
                for d2 in range(d1 + 1, len(config["SCHEDULING_DAYS"])):
                    is_active_1 = meetings[(sub.subject_id, s, d1)]["is_active"]
                    is_active_2 = meetings[(sub.subject_id, s, d2)]["is_active"]

                    if abs(d2 - d1) == 1:
                        model.AddBoolOr([is_active_1.Not(),is_active_2.Not()])
#================================== END OF MEETING SEPARATION CONSTRAINTS ==================================

#================================== START OF ROOM CAPACITY CONSTRAINT [HARD] ==================================
    # Room capacity enforcement using Element constraint (optimized)
    room_capacities = [r.capacity for r in rooms] + [9999]  # Dummy room has "infinite" capacity

    for sub in subjects:
        for s in range(sub.ideal_num_sections):
            key = (sub.subject_id, s)
            has_batch = section_has_batch[key]
            
            total_students_in_section = sum(
                section_assignments[(sub.subject_id, s, b_idx)]
                for b_idx, batch in enumerate(batches)
                if any(subject.subject_id == sub.subject_id for subject in batch.subjects)
            )
            
            room_var = assigned_room[key]
            cap_var = model.NewIntVar(0, max(room_capacities), f"cap_{sub.subject_id}_s{s}")
            model.AddElement(room_var, room_capacities, cap_var)
            model.Add(total_students_in_section <= cap_var).OnlyEnforceIf(has_batch)

#================================== END OF ROOM CAPACITY CONSTRAINT ==================================

#================================== START OF MAX SUBJECTS PER FACULTY [HARD] ==================================
    # [HARD] Enforce max subjects per faculty (linked subjects count as one)
    canonical_subject = {}
    for sub in subjects:
        if sub.linked_subject_id:
            root = min(sub.subject_id, sub.linked_subject_id)
            canonical_subject[sub.subject_id] = root
            if sub.linked_subject_id not in canonical_subject:
                canonical_subject[sub.linked_subject_id] = root
        else:
            canonical_subject[sub.subject_id] = sub.subject_id

    for f_idx, fac in enumerate(faculty):
        if not fac.max_subjects or fac.max_subjects <= 0:
            continue

        subject_assigned_flags = {}
        
        for sub in subjects:
            canon_id = canonical_subject[sub.subject_id]
            if canon_id in subject_assigned_flags:
                continue
            
            flags_per_section = []
            for s in range(sub.ideal_num_sections):
                key = (sub.subject_id, s)
                if key in assigned_faculty:
                    teaches_section = model.NewBoolVar(f"teach_f{f_idx}_{canon_id}_s{s}")
                    model.Add(assigned_faculty[key] == f_idx).OnlyEnforceIf(teaches_section)
                    model.Add(assigned_faculty[key] != f_idx).OnlyEnforceIf(teaches_section.Not())
                    flags_per_section.append(teaches_section)
            
            if flags_per_section:
                flag = model.NewBoolVar(f"teaches_f{f_idx}_{canon_id}")
                model.AddMaxEquality(flag, flags_per_section)
                subject_assigned_flags[canon_id] = flag
        
        if subject_assigned_flags:
            model.Add(sum(subject_assigned_flags.values()) <= fac.max_subjects)
#================================== END OF MAX SUBJECTS PER FACULTY ==================================

#================================== START OF NON-PREFERRED SUBJECT TRACKING [SOFT] ==================================
    # [SOFT] Track non-preferred subject assignments for penalty
    if build_soft_constraints:
        for f_idx, fac in enumerate(faculty):
            if not fac.preferred_subject_ids:
                continue

            for sub in subjects:
                if sub.subject_id in fac.preferred_subject_ids:
                    continue
                if sub.subject_id not in fac.qualified_subject_ids:
                    continue

                for s in range(sub.ideal_num_sections):
                    key = (sub.subject_id, s)
                    if key not in assigned_faculty:
                        continue

                    non_preferred = model.NewBoolVar(f"non_pref_f{f_idx}_{sub.subject_id}_s{s}")
                    model.Add(assigned_faculty[key] == f_idx).OnlyEnforceIf(non_preferred)
                    model.Add(assigned_faculty[key] != f_idx).OnlyEnforceIf(non_preferred.Not())
                    faculty_non_preferred_subject[f_idx][sub.subject_id].append(non_preferred)
#================================== END OF NON-PREFERRED SUBJECT TRACKING ==================================

#================================== START OF BANNED TIMES CONSTRAINT [HARD] ==================================
    # TODO: Re-implement banned times constraint using DRS or interval constraints
    # Previously enforced via slot grid: batch_class_at[b_idx][day_idx][slot_idx] == False
    # Need to implement using DRS intervals to block banned time periods
#================================== END OF BANNED TIMES CONSTRAINT ==================================

    #================================== START OF FACULTY HOURS CONSTRAINT [SOFT/HARD] ==================================
    # [SOFT] Minimize faculty overload hours, [HARD] Enforce minimum hours
    for f_idx, f in enumerate(faculty):
        meeting_minutes_terms = []
        qualified_subjects = faculty_qualified_subjects.get(f_idx, [])

        for sub in qualified_subjects:
            for s in range(sub.ideal_num_sections):
                for d_idx in range(len(config["SCHEDULING_DAYS"])):
                    key = (f_idx, sub.subject_id, s, d_idx)
                    if key not in active_for_faculty_map:
                        continue

                    duration_var = meetings[(sub.subject_id, s, d_idx)]["duration"]
                    active_var = active_for_faculty_map[key]
                    max_duration = duration_var.Proto().domain[-1]

                    minutes_worked = model.NewIntVar(
                        0,
                        max_duration,
                        f"minutes_f{f_idx}_{sub.subject_id}_s{s}_d{d_idx}",
                    )
                    model.Add(minutes_worked == duration_var).OnlyEnforceIf(active_var)
                    model.Add(minutes_worked == 0).OnlyEnforceIf(active_var.Not())
                    meeting_minutes_terms.append(minutes_worked)

        total_minutes_worked = sum(meeting_minutes_terms)

        max_minutes = f.max_hours * 60
        min_minutes = f.min_hours * 60

        # Soft: Track over maximum hours
        model.Add(total_minutes_worked - max_minutes <= faculty_overload_minutes[f_idx]) 
       
        # Soft: Track under minimum hours
        if f.min_hours > 0: 
            model.Add(min_minutes - total_minutes_worked <= faculty_underfill_minutes[f_idx])
        else:
            model.Add(faculty_underfill_minutes[f_idx] == 0)
        
        # TOGGLE: Uncomment to enforce hard maximum hours
        if f.max_hours > 0: 
            model.Add(max_minutes >= total_minutes_worked)
    #================================== END OF FACULTY HOURS CONSTRAINT ==================================

    #================================== START OF SECTION FILL TRACKING [SOFT] ==================================
    if build_soft_constraints:
        # [SOFT] Track section overfill violations - uses max_enrollment from subject
        for sub in subjects:
            max_students = sub.max_enrollment if sub.max_enrollment and sub.max_enrollment > 0 else 40
            
            for s in range(sub.ideal_num_sections):
                key = (sub.subject_id, s)
                has_batch = section_has_batch[key]
                
                total_students_in_section = sum(
                    section_assignments[(sub.subject_id, s, b_idx)]
                    for b_idx, batch in enumerate(batches)
                    if any(subj.subject_id == sub.subject_id for subj in batch.subjects)
                )
                
                model.Add(section_overfill_students[key] >= total_students_in_section - max_students).OnlyEnforceIf(has_batch)
                model.Add(section_overfill_students[key] == 0).OnlyEnforceIf(has_batch.Not())

    if build_soft_constraints:
        # [SOFT] Track section underfill violations - hardcoded minimum of 20 students for all subjects
        MIN_SECTION_STUDENTS = 20
        for sub in subjects:
            for s in range(sub.ideal_num_sections):
                key = (sub.subject_id, s)
                has_batch = section_has_batch[key]
                
                total_students_in_section = sum(
                    section_assignments[(sub.subject_id, s, b_idx)]
                    for b_idx, batch in enumerate(batches)
                    if any(subj.subject_id == sub.subject_id for subj in batch.subjects)
                )
                
                model.Add(section_underfill_students[key] >= MIN_SECTION_STUDENTS - total_students_in_section).OnlyEnforceIf(has_batch)
                model.Add(section_underfill_students[key] == 0).OnlyEnforceIf(has_batch.Not())
    #================================== END OF SECTION FILL TRACKING ==================================

    #================================== START OF LOGICAL ENGINE - SOFT CONSTRAINTS ==================================
    if build_soft_constraints:
        print("\n6. Adding Logical Engine Soft Constraints (Min Class, Max Gap)...")
        
        # Calculate slot limits from config
        MIN_CLASS_SLOTS = int((config["MIN_CONTINUOUS_CLASS_HOURS"] * 60) / config["TIME_GRANULARITY_MINUTES"])
        MAX_GAP_SLOTS = int((config["MAX_GAP_HOURS"] * 60) / config["TIME_GRANULARITY_MINUTES"])
        
        print(f"   Min continuous class: {config['MIN_CONTINUOUS_CLASS_HOURS']}h = {MIN_CLASS_SLOTS} slots")
        print(f"   Max gap: {config['MAX_GAP_HOURS']}h = {MAX_GAP_SLOTS} slots")
        
        total_min_class_violations = 0
        total_max_gap_violations = 0
        
        # Faculty soft constraints
        for f_idx, faculty_member in enumerate(faculty):
            for day_idx in range(len(config["SCHEDULING_DAYS"])):
                slots = faculty_ghost_grid[(f_idx, day_idx)]
                N = len(slots)
                
                for i in range(N):
                    time_slot = slots[i]["time_slot"]
                    active_streak = faculty_active_streak[(f_idx, day_idx)][i]
                    vacant_streak = faculty_vacant_streak[(f_idx, day_idx)][i]
                    
                    # SOFT: Min Continuous Class
                    # BlockEnds = (TimeSlots[i] == 1) AND (i == N-1 OR TimeSlots[i+1] == 0)
                    # Penalty: Max(0, MIN_CLASS_SLOTS - ActiveStreak[i])
                    block_ends = model.NewBoolVar(f"block_ends_f{f_idx}_d{day_idx}_i{i}")
                    
                    if i == N - 1:
                        # Last slot: block_ends = time_slot
                        model.Add(block_ends == 1).OnlyEnforceIf(time_slot)
                        model.Add(block_ends == 0).OnlyEnforceIf(time_slot.Not())
                    else:
                        next_time_slot = slots[i+1]["time_slot"]
                        # block_ends = (time_slot == 1) AND (next_time_slot == 0)
                        model.AddBoolAnd([time_slot, next_time_slot.Not()]).OnlyEnforceIf(block_ends)
                        model.AddBoolOr([time_slot.Not(), next_time_slot]).OnlyEnforceIf(block_ends.Not())
                    
                    # Violation: Max(0, MIN_CLASS_SLOTS - active_streak)
                    violation = model.NewIntVar(0, MIN_CLASS_SLOTS, f"min_class_viol_f{f_idx}_d{day_idx}_i{i}")
                    model.Add(violation >= MIN_CLASS_SLOTS - active_streak).OnlyEnforceIf(block_ends)
                    model.Add(violation == 0).OnlyEnforceIf(block_ends.Not())
                    faculty_under_minimum_block[f_idx][day_idx].append(violation)
                    total_min_class_violations += 1
                    
                    # SOFT: Max Gap
                    # GapEndsHere = (TimeSlots[i] == 0) AND (i < N-1 AND TimeSlots[i+1] == 1)
                    # Penalty: Max(0, VacantStreak[i] - MAX_GAP_SLOTS)
                    if i < N - 1:
                        next_time_slot = slots[i+1]["time_slot"]
                        gap_ends_here = model.NewBoolVar(f"gap_ends_soft_f{f_idx}_d{day_idx}_i{i}")
                        
                        # gap_ends_here = (time_slot == 0) AND (next_time_slot == 1)
                        model.AddBoolAnd([time_slot.Not(), next_time_slot]).OnlyEnforceIf(gap_ends_here)
                        model.AddBoolOr([time_slot, next_time_slot.Not()]).OnlyEnforceIf(gap_ends_here.Not())
                        
                        # Violation: Max(0, vacant_streak - MAX_GAP_SLOTS)
                        violation = model.NewIntVar(0, 100, f"max_gap_viol_f{f_idx}_d{day_idx}_i{i}")
                        model.Add(violation >= vacant_streak - MAX_GAP_SLOTS).OnlyEnforceIf(gap_ends_here)
                        model.Add(violation == 0).OnlyEnforceIf(gap_ends_here.Not())
                        faculty_excess_gaps[f_idx][day_idx].append(violation)
                        total_max_gap_violations += 1
        
        # Batch soft constraints
        for b_idx, batch in enumerate(batches):
            for day_idx in range(len(config["SCHEDULING_DAYS"])):
                slots = batch_ghost_grid[(b_idx, day_idx)]
                N = len(slots)
                
                for i in range(N):
                    time_slot = slots[i]["time_slot"]
                    active_streak = batch_active_streak[(b_idx, day_idx)][i]
                    vacant_streak = batch_vacant_streak[(b_idx, day_idx)][i]
                    
                    # SOFT: Min Continuous Class
                    block_ends = model.NewBoolVar(f"block_ends_b{b_idx}_d{day_idx}_i{i}")
                    
                    if i == N - 1:
                        model.Add(block_ends == 1).OnlyEnforceIf(time_slot)
                        model.Add(block_ends == 0).OnlyEnforceIf(time_slot.Not())
                    else:
                        next_time_slot = slots[i+1]["time_slot"]
                        model.AddBoolAnd([time_slot, next_time_slot.Not()]).OnlyEnforceIf(block_ends)
                        model.AddBoolOr([time_slot.Not(), next_time_slot]).OnlyEnforceIf(block_ends.Not())
                    
                    violation = model.NewIntVar(0, MIN_CLASS_SLOTS, f"min_class_viol_b{b_idx}_d{day_idx}_i{i}")
                    model.Add(violation >= MIN_CLASS_SLOTS - active_streak).OnlyEnforceIf(block_ends)
                    model.Add(violation == 0).OnlyEnforceIf(block_ends.Not())
                    batch_under_minimum_block[b_idx][day_idx].append(violation)
                    total_min_class_violations += 1
                    
                    # SOFT: Max Gap
                    if i < N - 1:
                        next_time_slot = slots[i+1]["time_slot"]
                        gap_ends_here = model.NewBoolVar(f"gap_ends_soft_b{b_idx}_d{day_idx}_i{i}")
                        
                        model.AddBoolAnd([time_slot.Not(), next_time_slot]).OnlyEnforceIf(gap_ends_here)
                        model.AddBoolOr([time_slot, next_time_slot.Not()]).OnlyEnforceIf(gap_ends_here.Not())
                        
                        violation = model.NewIntVar(0, 100, f"max_gap_viol_b{b_idx}_d{day_idx}_i{i}")
                        model.Add(violation >= vacant_streak - MAX_GAP_SLOTS).OnlyEnforceIf(gap_ends_here)
                        model.Add(violation == 0).OnlyEnforceIf(gap_ends_here.Not())
                        batch_excess_gaps[b_idx][day_idx].append(violation)
                        total_max_gap_violations += 1
        
        print(f"   Min Continuous Class violation trackers: {total_min_class_violations}")
        print(f"   Max Gap violation trackers: {total_max_gap_violations}")
    #================================== END OF LOGICAL ENGINE - SOFT CONSTRAINTS ==================================

    # Collect structural slack variables for Pass 1
    structural_violations = []
    
    # Structural violations: dummy faculty, dummy room, duration, day gaps
    for key, slack_var in sorted(is_dummy_faculty.items()):
        structural_violations.append(slack_var)
    for key, slack_var in sorted(is_dummy_room.items()):
        structural_violations.append(slack_var)
    for key, slack_var in sorted(duration_violations.items()):
        structural_violations.append(slack_var)
    for f_idx in sorted(faculty_day_gaps.keys()):
        for slack_var in faculty_day_gaps[f_idx]:
            structural_violations.append(slack_var)
    for b_idx in sorted(batch_day_gaps.keys()):
        for slack_var in batch_day_gaps[b_idx]:
            structural_violations.append(slack_var)
    
    # Pass mode controls: "pass1" only, "pass2" only (with limit), or "full" (both)
    total_structural_violations = model.NewIntVar(0, len(structural_violations), "total_structural_violations")
    model.Add(total_structural_violations == sum(structural_violations))
    
    # Prepare log directory
    if output_folder:
        log_dir = output_folder
    else:
        log_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(log_dir, exist_ok=True)
    
    # Prepare log file paths
    model_stats_file = os.path.join(log_dir, "model_statistics.txt")
    presolve_log_file = os.path.join(log_dir, "presolve_log.txt")
    search_log_file = os.path.join(log_dir, "search_log.txt")
    optimization_log_file = os.path.join(log_dir, "optimization_log.txt")
    
    # Solver configurations
    solver = cp_model.CpSolver()
    if random_seed is not None:
        solver.parameters.random_seed = random_seed
    solver.parameters.num_search_workers = 1 if deterministic_mode else 12
    solver.parameters.cp_model_presolve = True
    
    # Configure logging to files based on toggles
    if SHOW_PRESOLVE_LOGS or SHOW_SEARCH_LOGS or SHOW_OPTIMIZATION_LOGS:
        solver.parameters.log_search_progress = True
        # We'll capture logs using a custom approach below
    else:
        solver.parameters.log_search_progress = False
    
    # Print model statistics to file if enabled
    if SHOW_MODEL_STATISTICS:
        import sys
        with open(model_stats_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("MODEL STATISTICS\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            try:
                proto = model.Proto()
                num_vars = len(proto.variables)
                num_constraints = len(proto.constraints)
                f.write(f"Variables: {num_vars:,}\n")
                f.write(f"Constraints: {num_constraints:,}\n")
                f.write(f"Search workers: {solver.parameters.num_search_workers}\n")
                f.write(f"Deterministic mode: {deterministic_mode}\n")
                f.write(f"Random seed: {random_seed if random_seed else 'default'}\n\n")
                
                # Count constraint types
                constraint_types = {}
                for c in proto.constraints:
                    c_type = c.WhichOneof('constraint')
                    constraint_types[c_type] = constraint_types.get(c_type, 0) + 1
                
                f.write("\nConstraint breakdown:\n")
                f.write("-" * 40 + "\n")
                for c_type, count in sorted(constraint_types.items(), key=lambda x: -x[1]):
                    f.write(f"  {c_type}: {count:,}\n")
                    
            except Exception as e:
                f.write(f"\nError generating statistics: {e}\n")
        
        print(f"📊 Model statistics saved to: {model_stats_file}")
        sys.stdout.flush()
    # Try to validate the model before solving
    print("🔍 Validating model...")
    sys.stdout.flush()
    try:
        model_str = model.Proto()  # This will fail if model has issues
        print(f"✓ Model proto generated successfully")
        sys.stdout.flush()
    except Exception as e:
        print(f"❌ Model validation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        raise
    
    # Setup log callback to capture solver output to files
    solver_log_file = None
    if SHOW_PRESOLVE_LOGS or SHOW_SEARCH_LOGS or SHOW_OPTIMIZATION_LOGS:
        # Determine which log file to use based on current pass
        if pass_mode in ["pass1", "full"]:
            solver_log_file = os.path.join(log_dir, "solver_pass1.log")
        else:
            solver_log_file = os.path.join(log_dir, "solver_pass2.log")
        
        # Create/clear the log file
        with open(solver_log_file, 'w', encoding='utf-8') as f:
            f.write(f"CP-SAT Solver Log - {pass_mode.upper()}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
        
        # Set log callback to write to file
        def log_callback(msg):
            with open(solver_log_file, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')
        
        solver.log_callback = log_callback
        print(f"📝 Solver logs will be saved to: {solver_log_file}")
    
    # PASS 1: MINIMIZE STRUCTURAL VIOLATIONS
    if pass_mode in ["pass1", "full"]:
        print("\n" + "="*60)
        print("PASS 1: MINIMIZING STRUCTURAL VIOLATIONS")
        print("="*60)
        print(f"Structural slack variables: {len(structural_violations)}, Pass mode: {pass_mode}")
        
        model.Minimize(total_structural_violations)
        
        pass1_time_limit = (time_limit / 2) if (pass_mode == "full" and time_limit) else time_limit
        if pass1_time_limit:
            solver.parameters.max_time_in_seconds = pass1_time_limit
        print(f"Seed: {random_seed if random_seed else 'default'}")
        
        log_file_path = os.path.join(log_dir, "solution_log_pass1.txt")
        print(f"Log file: {log_file_path}")
        import sys
        sys.stdout.flush()
        
        print("Creating solution callback...")
        sys.stdout.flush()
        solution_printer_pass1 = SolutionPrinterCallback(total_structural_violations, log_file_path=log_file_path)
        
        print(f"Starting solver with time limit: {pass1_time_limit}s...")
        sys.stdout.flush()
        
        try:
            status_pass1 = solver.Solve(model, solution_printer_pass1)
            print(f"Solver finished with status code: {status_pass1}")
            sys.stdout.flush()
        except Exception as e:
            print(f"ERROR: Solver crashed with exception: {e}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            raise
        
        write_solver_diagnostics(solver, model, status_pass1, "PASS 1 (Structural)", output_dir=log_dir)
        solution_printer_pass1.write_stats_summary(os.path.join(log_dir, "solver_stats_pass1.txt"))
        print(f"\nPass 1 Status: {solver.StatusName(status_pass1)}")
        
        # Export debug files for Pass 1 (regardless of status)
        # DRS debug export removed - was causing NameError
        
        # Ghost Grid Debug - Pass 1
        print_ghost_grid_debug(faculty_ghost_grid, batch_ghost_grid, faculty, batches, config, 
                              solver, faculty_active_streak, faculty_vacant_streak,
                              batch_active_streak, batch_vacant_streak,
                              output_dir=log_dir, pass_name="pass1")
        
        print_all_meetings_debug(meetings, assigned_faculty, assigned_room, section_assignments,
                                 faculty, rooms, batches, subjects_map, config, solver,
                                 output_dir=log_dir, pass_name="pass1")
        
        if status_pass1 not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            print("Pass 1 failed to find a feasible solution!")
            return status_pass1, solver, {
                "meetings": meetings,
                "assigned_faculty": assigned_faculty,
                "assigned_room": assigned_room,
                "section_assignments": section_assignments,
                "violations": {},
                "total_penalty": None,
                "pass1_structural_violations": None,
                "pass2_preference_penalty": None,
                "DUMMY_FACULTY_IDX": DUMMY_FACULTY_IDX,
                "DUMMY_ROOM_IDX": DUMMY_ROOM_IDX,
            }
        
        min_structural_violations = solver.Value(total_structural_violations)
        print(f"Pass 1 Result: min_structural = {min_structural_violations}")
        
        # PASS 1 ONLY: Return here if pass_mode="pass1"
        if pass_mode == "pass1":
            print("\n" + "="*60)
            print("PASS 1 COMPLETE - Returning structural minimum for Pass 2")
            print("="*60)
            return status_pass1, solver, {
                "meetings": meetings,
                "assigned_faculty": assigned_faculty,
                "assigned_room": assigned_room,
                "section_assignments": section_assignments,
                "violations": {
                    "duration_violations": duration_violations,
                    "is_dummy_faculty": is_dummy_faculty,
                    "is_dummy_room": is_dummy_room,
                    "faculty_day_gaps": faculty_day_gaps,
                    "batch_day_gaps": batch_day_gaps,
                },
                "total_penalty": None,
                "pass1_structural_violations": min_structural_violations,
                "pass2_preference_penalty": None,
                "DUMMY_FACULTY_IDX": DUMMY_FACULTY_IDX,
                "DUMMY_ROOM_IDX": DUMMY_ROOM_IDX,
                "section_has_batch": section_has_batch,
            }
    
    # PASS 2 SETUP: Use structural_limit if pass_mode="pass2"
    if pass_mode == "pass2":
        if structural_limit is None:
            raise ValueError("pass_mode='pass2' requires structural_limit!")
        min_structural_violations = structural_limit
        lock_mode = config.get("PASS2_LOCK_MODE", "exact")
        
        print("\n" + "="*60)
        print("PASS 2: USING STRUCTURAL LIMIT FROM PASS 1")
        print("="*60)
        print(f"Structural limit: {structural_limit}, Lock mode: {lock_mode}")
        
        if lock_mode == "exact":
            # EXACT MODE: Lock each structural slack variable to its Pass 1 value
            if pass1_hints:
                lock_count = 0
                print("\nLocking structural slack variables as hard constraints:")
                print("-"*100)
                
                for key, value in sorted(pass1_hints.get("is_dummy_faculty", {}).items()):
                    if key in is_dummy_faculty:
                        model.Add(is_dummy_faculty[key] == value)
                        lock_count += 1
                
                for key, value in sorted(pass1_hints.get("is_dummy_room", {}).items()):
                    if key in is_dummy_room:
                        model.Add(is_dummy_room[key] == value)
                        lock_count += 1
                
                for key, value in sorted(pass1_hints.get("duration_violations", {}).items()):
                    if key in duration_violations:
                        model.Add(duration_violations[key] == value)
                        lock_count += 1
                
                for f_idx, gap_values in sorted(pass1_hints.get("faculty_day_gaps", {}).items()):
                    if f_idx in faculty_day_gaps:
                        for day_offset, value in enumerate(gap_values):
                            if day_offset < len(faculty_day_gaps[f_idx]):
                                model.Add(faculty_day_gaps[f_idx][day_offset] == value)
                                lock_count += 1
                
                for b_idx, gap_values in sorted(pass1_hints.get("batch_day_gaps", {}).items()):
                    if b_idx in batch_day_gaps:
                        for day_offset, value in enumerate(gap_values):
                            if day_offset < len(batch_day_gaps[b_idx]):
                                model.Add(batch_day_gaps[b_idx][day_offset] == value)
                                lock_count += 1
                
                print(f"Locked {lock_count} structural constraints")
            else:
                print("No Pass 1 structural values provided to lock")
        
        elif lock_mode == "limit":
            model.Add(total_structural_violations <= min_structural_violations)
            print(f"Added limit constraint: total_structural_violations <= {min_structural_violations}")
        
        else:
            raise ValueError(f"Invalid PASS2_LOCK_MODE: '{lock_mode}'. Must be 'exact' or 'limit'.")
    
    # PASS 2: Build preference penalty objective and solve
    total_penalty = model.NewIntVar(0, 10000000, "total_penalty")
    
    # Convert per-hour penalties to per-slot based on granularity
    slots_per_hour = 60 / config["TIME_GRANULARITY_MINUTES"]
    excess_class_penalty = int(config["ConstraintPenalties"]["EXCESS_CONTINUOUS_CLASS_PER_HOUR"] / slots_per_hour)
    under_min_block_penalty = int(config["ConstraintPenalties"]["UNDER_MINIMUM_BLOCK_PER_HOUR"] / slots_per_hour)
    underfill_gap_penalty = int(config["ConstraintPenalties"]["UNDERFILL_GAP_PER_HOUR"] / slots_per_hour)
    excess_gap_penalty = int(config["ConstraintPenalties"]["EXCESS_GAP_PER_HOUR"] / slots_per_hour)
    
    penalties = []
    penalties.extend([v * config["ConstraintPenalties"]["FACULTY_OVERLOAD_PER_MINUTE"] for v in faculty_overload_minutes])
    penalties.extend([v * config["ConstraintPenalties"]["FACULTY_OVERLOAD_PER_MINUTE"] for v in faculty_underfill_minutes])
    penalties.extend([v * config["ConstraintPenalties"]["ROOM_OVERCAPACITY_PER_STUDENT"] for k, v in sorted(room_overcapacity_students.items())])
    penalties.extend([v * config["ConstraintPenalties"]["SECTION_OVERFILL_PER_STUDENT"] for k, v in sorted(section_overfill_students.items())])
    penalties.extend([v * config["ConstraintPenalties"]["SECTION_UNDERFILL_PER_STUDENT"] for k, v in sorted(section_underfill_students.items())])
    penalties.extend([v * under_min_block_penalty for entity_idx in sorted(faculty_under_minimum_block.keys()) for day_idx in sorted(faculty_under_minimum_block[entity_idx].keys()) for v in faculty_under_minimum_block[entity_idx][day_idx]])
    penalties.extend([v * under_min_block_penalty for entity_idx in sorted(batch_under_minimum_block.keys()) for day_idx in sorted(batch_under_minimum_block[entity_idx].keys()) for v in batch_under_minimum_block[entity_idx][day_idx]])
    penalties.extend([v * excess_gap_penalty for entity_idx in sorted(faculty_excess_gaps.keys()) for day_idx in sorted(faculty_excess_gaps[entity_idx].keys()) for v in faculty_excess_gaps[entity_idx][day_idx]])
    penalties.extend([v * excess_gap_penalty for entity_idx in sorted(batch_excess_gaps.keys()) for day_idx in sorted(batch_excess_gaps[entity_idx].keys()) for v in batch_excess_gaps[entity_idx][day_idx]])
    penalties.extend([flag * config["ConstraintPenalties"]["NON_PREFERRED_SUBJECT_PER_SECTION"] for f_idx in sorted(faculty_non_preferred_subject.keys()) for sub_id in sorted(faculty_non_preferred_subject[f_idx].keys()) for flag in faculty_non_preferred_subject[f_idx][sub_id]])
    
    model.Add(total_penalty == sum(penalties))
    model.Minimize(total_penalty)
    
    if time_limit:
        solver.parameters.max_time_in_seconds = time_limit
    
    log_file_path_pass2 = os.path.join(log_dir, "solution_log_pass2.txt")
    solution_printer_pass2 = SolutionPrinterCallback(total_penalty, log_file_path=log_file_path_pass2)
    status = solver.Solve(model, solution_printer_pass2)
    
    write_solver_diagnostics(solver, model, status, "PASS 2 (Preferences)", output_dir=log_dir)
    
    # Write detailed statistics summary
    solution_printer_pass2.write_stats_summary(os.path.join(log_dir, "solver_stats_pass2.txt"))
    
    print(f"\nPass 2 Status: {solver.StatusName(status)}")
    pass2_preference_penalty = None
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        pass2_preference_penalty = solver.Value(total_penalty)
        print(f"Pass 2 Result: penalty = {pass2_preference_penalty}")
    
    print(f"\nSolution log exported to: {log_file_path_pass2}")
    
    # Export debug files for Pass 2
    # DRS debug export removed - was causing NameError
    
    # Ghost Grid Debug - Pass 2
    print_ghost_grid_debug(faculty_ghost_grid, batch_ghost_grid, faculty, batches, config, 
                          solver, faculty_active_streak, faculty_vacant_streak,
                          batch_active_streak, batch_vacant_streak,
                          output_dir=log_dir, pass_name="pass2")
    
    print_all_meetings_debug(meetings, assigned_faculty, assigned_room, section_assignments,
                             faculty, rooms, batches, subjects_map, config, solver,
                             output_dir=log_dir, pass_name="pass2")
    #================================== END OF LEXICOGRAPHIC OPTIMIZATION ==================================

    return status, solver, {
        "meetings": meetings, 
        "assigned_faculty": assigned_faculty, 
        "assigned_room": assigned_room, 
        "section_assignments": section_assignments,
        "violations": {
            "faculty_overload": faculty_overload_minutes,
            "faculty_underfill": faculty_underfill_minutes,
            "room_overcapacity": room_overcapacity_students,
            "section_overfill": section_overfill_students, 
            "section_underfill": section_underfill_students,
            "faculty_under_minimum_block": faculty_under_minimum_block,
            "batch_under_minimum_block": batch_under_minimum_block,
            "faculty_excess_gaps": faculty_excess_gaps,
            "batch_excess_gaps": batch_excess_gaps,
            "faculty_non_preferred_subject": faculty_non_preferred_subject,
            "faculty_day_gaps": faculty_day_gaps,
            "batch_day_gaps": batch_day_gaps,
            "duration_violations": duration_violations,
            "is_dummy_faculty": is_dummy_faculty,
            "is_dummy_room": is_dummy_room
        },
        "total_penalty": total_penalty,
        "pass1_structural_violations": min_structural_violations,
        "pass2_preference_penalty": pass2_preference_penalty,
        "DUMMY_FACULTY_IDX": DUMMY_FACULTY_IDX,
        "DUMMY_ROOM_IDX": DUMMY_ROOM_IDX,
        "section_has_batch": section_has_batch,
    }