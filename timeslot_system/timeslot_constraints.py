"""
Time Slot Constraints - Logical Constraint Layer

This module adds hard and soft constraints based on streak tracking data.
It reads from streak variables and time_slot arrays to enforce scheduling rules.

Hard Constraints:
    - Max continuous class hours
    - Min gap between classes

Soft Constraints (penalties):
    - Min continuous class hours
    - Max gap between classes
"""

import collections

def add_hard_constraints(model, timeslot_data, streak_data, faculty, batches):
    """
    Add hard constraints for max continuous class and min gap.
    
    Args:
        model: CP-SAT model instance
        timeslot_data: Dictionary from controller with faculty_data and batch_data
        streak_data: Dictionary from streak_tracker with streak variables
        faculty: List of Faculty objects
        batches: List of Batch objects
        
    Returns:
        Dictionary with constraint counts for reporting
    """
    
    config = timeslot_data['config']
    faculty_data = timeslot_data['faculty_data']
    batch_data = timeslot_data['batch_data']
    
    faculty_active_streak = streak_data['faculty_active_streak']
    faculty_vacant_streak = streak_data['faculty_vacant_streak']
    batch_active_streak = streak_data['batch_active_streak']
    batch_vacant_streak = streak_data['batch_vacant_streak']
    
    print("\n[Timeslot Constraints] Adding hard constraints (Max Class, Min Gap)...")
    
    # Calculate slot limits from config
    TIME_GRANULARITY = config.get("TIME_GRANULARITY_MINUTES", 10)
    MAX_CLASS_SLOTS = int((config["MAX_CONTINUOUS_CLASS_HOURS"] * 60) / TIME_GRANULARITY)
    MIN_GAP_SLOTS = int((config["MIN_GAP_HOURS"] * 60) / TIME_GRANULARITY)
    
    print(f"   Max continuous class: {config['MAX_CONTINUOUS_CLASS_HOURS']}h = {MAX_CLASS_SLOTS} slots")
    print(f"   Min gap: {config['MIN_GAP_HOURS']}h = {MIN_GAP_SLOTS} slots")
    
    total_max_class_constraints = 0
    total_min_gap_constraints = 0
    
    # Track gap_ends_here for both faculty and batches
    faculty_gap_ends_here = {}
    batch_gap_ends_here = {}
    
    # Faculty constraints
    for f_idx, faculty_member in enumerate(faculty):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = faculty_data[(f_idx, day_idx)]
            N = len(slots)
            
            faculty_gap_ends_here[(f_idx, day_idx)] = []
            
            for i in range(N):
                time_slot = slots[i]["time_slot"]
                active_streak = faculty_active_streak[(f_idx, day_idx)][i]
                vacant_streak = faculty_vacant_streak[(f_idx, day_idx)][i]
                
                # HARD: Max Continuous Class - ActiveStreak[i] <= MAX_CLASS_SLOTS
                model.Add(active_streak <= MAX_CLASS_SLOTS)
                total_max_class_constraints += 1
                
                # HARD: Min Gap - VacantStreak[i] >= MIN_GAP_SLOTS when gap ends
                # GapEndsHere = (TimeSlots[i] == 0) AND (next_time_slot == 1) AND (encountered_class_before)
                if i < N - 1:
                    next_time_slot = slots[i+1]["time_slot"]
                    
                    # Check if we've encountered a class before (VacantStreak[i] < i)
                    encountered_class_before = model.NewBoolVar(f"encountered_class_f{f_idx}_d{day_idx}_i{i}")
                    model.Add(vacant_streak < i).OnlyEnforceIf(encountered_class_before)
                    model.Add(vacant_streak >= i).OnlyEnforceIf(encountered_class_before.Not())
                    
                    gap_ends_here = model.NewBoolVar(f"gap_ends_f{f_idx}_d{day_idx}_i{i}")
                    
                    # gap_ends_here = (time_slot == 0) AND (next_time_slot == 1) AND (encountered_class_before)
                    model.AddBoolAnd([time_slot.Not(), next_time_slot, encountered_class_before]).OnlyEnforceIf(gap_ends_here)
                    model.AddBoolOr([time_slot, next_time_slot.Not(), encountered_class_before.Not()]).OnlyEnforceIf(gap_ends_here.Not())
                    
                    # If gap_ends_here, then vacant_streak >= MIN_GAP_SLOTS
                    model.Add(vacant_streak >= MIN_GAP_SLOTS).OnlyEnforceIf(gap_ends_here)
                    total_min_gap_constraints += 1
                    
                    faculty_gap_ends_here[(f_idx, day_idx)].append(gap_ends_here)
                else:
                    # Last slot has no "next" - cannot end a gap before a class
                    faculty_gap_ends_here[(f_idx, day_idx)].append(None)
    
    # Batch constraints
    for b_idx, batch in enumerate(batches):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = batch_data[(b_idx, day_idx)]
            N = len(slots)
            
            batch_gap_ends_here[(b_idx, day_idx)] = []
            
            for i in range(N):
                time_slot = slots[i]["time_slot"]
                active_streak = batch_active_streak[(b_idx, day_idx)][i]
                vacant_streak = batch_vacant_streak[(b_idx, day_idx)][i]
                
                # HARD: Max Continuous Class - ActiveStreak[i] <= MAX_CLASS_SLOTS
                model.Add(active_streak <= MAX_CLASS_SLOTS)
                total_max_class_constraints += 1
                
                # HARD: Min Gap
                if i < N - 1:
                    next_time_slot = slots[i+1]["time_slot"]
                    
                    # Check if we've encountered a class before (VacantStreak[i] < i)
                    encountered_class_before = model.NewBoolVar(f"encountered_class_b{b_idx}_d{day_idx}_i{i}")
                    model.Add(vacant_streak < i).OnlyEnforceIf(encountered_class_before)
                    model.Add(vacant_streak >= i).OnlyEnforceIf(encountered_class_before.Not())
                    
                    gap_ends_here = model.NewBoolVar(f"gap_ends_b{b_idx}_d{day_idx}_i{i}")
                    
                    # gap_ends_here = (time_slot == 0) AND (next_time_slot == 1) AND (encountered_class_before)
                    model.AddBoolAnd([time_slot.Not(), next_time_slot, encountered_class_before]).OnlyEnforceIf(gap_ends_here)
                    model.AddBoolOr([time_slot, next_time_slot.Not(), encountered_class_before.Not()]).OnlyEnforceIf(gap_ends_here.Not())
                    
                    model.Add(vacant_streak >= MIN_GAP_SLOTS).OnlyEnforceIf(gap_ends_here)
                    total_min_gap_constraints += 1
                    
                    batch_gap_ends_here[(b_idx, day_idx)].append(gap_ends_here)
                else:
                    # Last slot has no "next" - cannot end a gap before a class
                    batch_gap_ends_here[(b_idx, day_idx)].append(None)
    
    print(f"   Max Continuous Class constraints: {total_max_class_constraints}")
    print(f"   Min Gap constraints: {total_min_gap_constraints}")
    
    return {
        'max_class_constraints': total_max_class_constraints,
        'min_gap_constraints': total_min_gap_constraints,
        'faculty_gap_ends_here': faculty_gap_ends_here,
        'batch_gap_ends_here': batch_gap_ends_here
    }


def add_soft_constraints(model, timeslot_data, streak_data, faculty, batches, violation_trackers):
    """
    Add soft constraints for min continuous class and max gap (with penalty tracking).
    
    Args:
        model: CP-SAT model instance
        timeslot_data: Dictionary from controller with faculty_data and batch_data
        streak_data: Dictionary from streak_tracker with streak variables
        faculty: List of Faculty objects
        batches: List of Batch objects
        violation_trackers: Dictionary containing violation tracking structures
        
    Returns:
        Dictionary with constraint counts for reporting
    """
    
    config = timeslot_data['config']
    faculty_data = timeslot_data['faculty_data']
    batch_data = timeslot_data['batch_data']
    
    faculty_active_streak = streak_data['faculty_active_streak']
    faculty_vacant_streak = streak_data['faculty_vacant_streak']
    batch_active_streak = streak_data['batch_active_streak']
    batch_vacant_streak = streak_data['batch_vacant_streak']
    
    faculty_under_minimum_block = violation_trackers['faculty_under_minimum_block']
    batch_under_minimum_block = violation_trackers['batch_under_minimum_block']
    faculty_excess_gaps = violation_trackers['faculty_excess_gaps']
    batch_excess_gaps = violation_trackers['batch_excess_gaps']
    
    print("\n[Timeslot Constraints] Adding soft constraints (Min Class, Max Gap)...")
    
    # Calculate slot limits from config
    TIME_GRANULARITY = config.get("TIME_GRANULARITY_MINUTES", 10)
    MIN_CLASS_SLOTS = int((config["MIN_CONTINUOUS_CLASS_HOURS"] * 60) / TIME_GRANULARITY)
    MAX_GAP_SLOTS = int((config["MAX_GAP_HOURS"] * 60) / TIME_GRANULARITY)
    
    print(f"   Min continuous class: {config['MIN_CONTINUOUS_CLASS_HOURS']}h = {MIN_CLASS_SLOTS} slots")
    print(f"   Max gap: {config['MAX_GAP_HOURS']}h = {MAX_GAP_SLOTS} slots")
    
    total_min_class_violations = 0
    total_max_gap_violations = 0
    
    # Track block_ends for debug reporting
    faculty_block_ends = {}
    batch_block_ends = {}
    
    # Faculty soft constraints
    for f_idx, faculty_member in enumerate(faculty):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = faculty_data[(f_idx, day_idx)]
            N = len(slots)
            
            faculty_block_ends[(f_idx, day_idx)] = []
            
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
                faculty_block_ends[(f_idx, day_idx)].append(block_ends)
                total_min_class_violations += 1
                
                # SOFT: Max Gap
                # GapEndsHere = (TimeSlots[i] == 0) AND (next_time_slot == 1) AND (encountered_class_before)
                # Penalty: Max(0, VacantStreak[i] - MAX_GAP_SLOTS)
                if i < N - 1:
                    next_time_slot = slots[i+1]["time_slot"]
                    
                    # Check if we've encountered a class before (VacantStreak[i] < i)
                    encountered_class_before = model.NewBoolVar(f"encountered_class_soft_f{f_idx}_d{day_idx}_i{i}")
                    model.Add(vacant_streak < i).OnlyEnforceIf(encountered_class_before)
                    model.Add(vacant_streak >= i).OnlyEnforceIf(encountered_class_before.Not())
                    
                    gap_ends_here = model.NewBoolVar(f"gap_ends_soft_f{f_idx}_d{day_idx}_i{i}")
                    
                    # gap_ends_here = (time_slot == 0) AND (next_time_slot == 1) AND (encountered_class_before)
                    model.AddBoolAnd([time_slot.Not(), next_time_slot, encountered_class_before]).OnlyEnforceIf(gap_ends_here)
                    model.AddBoolOr([time_slot, next_time_slot.Not(), encountered_class_before.Not()]).OnlyEnforceIf(gap_ends_here.Not())
                    
                    # Violation: Max(0, vacant_streak - MAX_GAP_SLOTS)
                    violation = model.NewIntVar(0, 100, f"max_gap_viol_f{f_idx}_d{day_idx}_i{i}")
                    model.Add(violation >= vacant_streak - MAX_GAP_SLOTS).OnlyEnforceIf(gap_ends_here)
                    model.Add(violation == 0).OnlyEnforceIf(gap_ends_here.Not())
                    faculty_excess_gaps[f_idx][day_idx].append(violation)
                    total_max_gap_violations += 1
    
    # Batch soft constraints
    for b_idx, batch in enumerate(batches):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = batch_data[(b_idx, day_idx)]
            N = len(slots)
            
            batch_block_ends[(b_idx, day_idx)] = []
            
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
                batch_block_ends[(b_idx, day_idx)].append(block_ends)
                total_min_class_violations += 1
                
                # SOFT: Max Gap
                if i < N - 1:
                    next_time_slot = slots[i+1]["time_slot"]
                    
                    # Check if we've encountered a class before (VacantStreak[i] < i)
                    encountered_class_before = model.NewBoolVar(f"encountered_class_soft_b{b_idx}_d{day_idx}_i{i}")
                    model.Add(vacant_streak < i).OnlyEnforceIf(encountered_class_before)
                    model.Add(vacant_streak >= i).OnlyEnforceIf(encountered_class_before.Not())
                    
                    gap_ends_here = model.NewBoolVar(f"gap_ends_soft_b{b_idx}_d{day_idx}_i{i}")
                    
                    # gap_ends_here = (time_slot == 0) AND (next_time_slot == 1) AND (encountered_class_before)
                    model.AddBoolAnd([time_slot.Not(), next_time_slot, encountered_class_before]).OnlyEnforceIf(gap_ends_here)
                    model.AddBoolOr([time_slot, next_time_slot.Not(), encountered_class_before.Not()]).OnlyEnforceIf(gap_ends_here.Not())
                    
                    violation = model.NewIntVar(0, 100, f"max_gap_viol_b{b_idx}_d{day_idx}_i{i}")
                    model.Add(violation >= vacant_streak - MAX_GAP_SLOTS).OnlyEnforceIf(gap_ends_here)
                    model.Add(violation == 0).OnlyEnforceIf(gap_ends_here.Not())
                    batch_excess_gaps[b_idx][day_idx].append(violation)
                    total_max_gap_violations += 1
    
    print(f"   Min Continuous Class violation trackers: {total_min_class_violations}")
    print(f"   Max Gap violation trackers: {total_max_gap_violations}")
    
    return {
        'min_class_violations': total_min_class_violations,
        'max_gap_violations': total_max_gap_violations,
        'faculty_block_ends': faculty_block_ends,
        'batch_block_ends': batch_block_ends
    }
