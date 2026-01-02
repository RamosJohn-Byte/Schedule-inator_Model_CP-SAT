"""
Streak Tracker - Logical Analysis Layer

This module analyzes time_slot boolean arrays to track consecutive class and gap streaks.
It reads from time_slot values (set by controllers) and produces streak tracking variables
that constraints can use.

Streak Variables:
    - active_streak[i]: Number of consecutive CLASS slots ending at position i
    - vacant_streak[i]: Number of consecutive GAP slots ending at position i
"""

def add_streak_tracking(model, timeslot_data, faculty, batches):
    """
    Build streak tracking variables based on time_slot arrays.
    
    This function reads the time_slot booleans from timeslot_data and creates
    IntVar arrays tracking consecutive occupied/vacant slots.
    
    Args:
        model: CP-SAT model instance
        timeslot_data: Dictionary from controller containing faculty_data and batch_data
        faculty: List of Faculty objects
        batches: List of Batch objects
        
    Returns:
        Dictionary containing:
            - 'faculty_active_streak': {(f_idx, day_idx) -> list of IntVars}
            - 'faculty_vacant_streak': {(f_idx, day_idx) -> list of IntVars}
            - 'batch_active_streak': {(b_idx, day_idx) -> list of IntVars}
            - 'batch_vacant_streak': {(b_idx, day_idx) -> list of IntVars}
    """
    
    config = timeslot_data['config']
    faculty_data = timeslot_data['faculty_data']
    batch_data = timeslot_data['batch_data']
    
    print("[Streak Tracker] Building streak analysis...")
    
    # Storage for streak variables
    faculty_active_streak = {}
    faculty_vacant_streak = {}
    batch_active_streak = {}
    batch_vacant_streak = {}
    
    # Faculty Streak Tracking
    for f_idx in range(len(faculty)):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = faculty_data[(f_idx, day_idx)]
            N = len(slots)
            
            faculty_active_streak[(f_idx, day_idx)] = []
            faculty_vacant_streak[(f_idx, day_idx)] = []
            
            for i in range(N):
                time_slot = slots[i]["time_slot"]  # 1 = CLASS, 0 = GAP
                
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
            slots = batch_data[(b_idx, day_idx)]
            N = len(slots)
            
            batch_active_streak[(b_idx, day_idx)] = []
            batch_vacant_streak[(b_idx, day_idx)] = []
            
            for i in range(N):
                time_slot = slots[i]["time_slot"]
                
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
    avg_slots_per_day = len(faculty_data[(0, 0)]) if faculty_data else 0
    total_intvars = (len(faculty) + len(batches)) * len(config["SCHEDULING_DAYS"]) * avg_slots_per_day * 2
    print(f"   Created streak tracking for {total_streak_vars} entity-day combinations")
    print(f"   Total streak IntVars: ~{total_intvars:,} (ActiveStreak + VacantStreak per slot)")
    
    return {
        'faculty_active_streak': faculty_active_streak,
        'faculty_vacant_streak': faculty_vacant_streak,
        'batch_active_streak': batch_active_streak,
        'batch_vacant_streak': batch_vacant_streak
    }
