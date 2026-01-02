"""
Ghost Block Controller - Interval-Based Vacancy Tracking

This controller implements the "Ghost Block" mechanism for setting time_slot values.

Concept:
    - Create fixed-position intervals representing VACANCY at every time slot
    - Add these "ghost" intervals to NoOverlap with class meetings
    - When a class overlaps a ghost → ghost must deactivate (vacancy killed)
    - time_slot[i] = NOT(ghost_active[i]) (inverter constraint)
    
Physics Engine Rules:
    1. COLLISION: Classes physically push ghosts out (NoOverlap)
    2. CONSERVATION: Ghost time + Class time = Total available time (checksum)
"""

def apply_ghostblock_controller(model, timeslot_data, faculty, batches, intervals_per_faculty, intervals_per_batch, is_assigned_faculty_map, is_assigned_batch_map, active_for_faculty_map, active_for_batch_map, meetings, faculty_qualified_subjects):
    """
    Create ghost intervals and link them to time_slot arrays via inverter constraints.
    Adds ghost intervals to NoOverlap constraints and enforces conservation laws.
    
    Args:
        model: CP-SAT model instance
        timeslot_data: Dictionary from timeslot_grid.create_timeslot_grid_data()
        faculty: List of Faculty objects
        batches: List of Batch objects
        intervals_per_faculty: Dict of f_idx -> list of interval vars
        intervals_per_batch: Dict of b_idx -> list of interval vars
        is_assigned_faculty_map: Dict of (f_idx, sub_id, s) -> BoolVar
        is_assigned_batch_map: Dict of (b_idx, sub_id, s) -> BoolVar
        active_for_faculty_map: Dict of (f_idx, sub_id, s, d_idx) -> BoolVar
        active_for_batch_map: Dict of (b_idx, sub_id, s, d_idx) -> BoolVar
        meetings: Dict of (sub_id, s, d_idx) -> meeting dict
        faculty_qualified_subjects: Dict of f_idx -> list of Subject objects
        
    Returns:
        Dictionary containing:
            - 'faculty_ghost_grid': {(f_idx, day_idx) -> list of ghost slot dicts}
            - 'batch_ghost_grid': {(b_idx, day_idx) -> list of ghost slot dicts}
    """
    
    config = timeslot_data['config']
    constants = timeslot_data['constants']
    
    MINUTES_IN_A_DAY = constants['MINUTES_IN_A_DAY']
    FRIDAY_IDX = constants['FRIDAY_IDX']
    TIME_GRANULARITY = constants['TIME_GRANULARITY']
    calculate_slots_for_day = constants['calculate_slots_for_day']
    
    print("\n[Ghost Block Controller] Creating ghost intervals...")
    
    # Storage for ghost grids
    faculty_ghost_grid = {}
    batch_ghost_grid = {}
    
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
                
                # Add ghost interval to faculty's interval list for NoOverlap
                intervals_per_faculty[f_idx].append(ghost_interval)
            
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
                
                # Add ghost interval to batch's interval list for NoOverlap
                intervals_per_batch[b_idx].append(ghost_interval)
            
            batch_ghost_grid[(b_idx, day_idx)] = ghost_slots
    
    # Print Ghost Blocks variable count
    total_faculty_ghost_vars = len(faculty) * len(config["SCHEDULING_DAYS"]) * calculate_slots_for_day(0, config) * 3
    total_batch_ghost_vars = len(batches) * len(config["SCHEDULING_DAYS"]) * calculate_slots_for_day(0, config) * 3
    print(f"👻 Ghost Blocks created:")
    print(f"   Faculty: {len(faculty)} × {len(config['SCHEDULING_DAYS'])} days × {calculate_slots_for_day(0, config)} slots × 3 vars = ~{total_faculty_ghost_vars:,} variables")
    print(f"   Batches: {len(batches)} × {len(config['SCHEDULING_DAYS'])} days × {calculate_slots_for_day(0, config)} slots × 3 vars = ~{total_batch_ghost_vars:,} variables")
    print(f"   Total Ghost variables: ~{total_faculty_ghost_vars + total_batch_ghost_vars:,}")
    
    # Store grids in timeslot_data for downstream consumers
    timeslot_data['faculty_data'] = faculty_ghost_grid
    timeslot_data['batch_data'] = batch_ghost_grid
    
    # Add conservation of time constraints
    print("\n[Ghost Block Controller] Adding conservation of time constraints...")
    
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
    
    return {
        'controller_type': 'ghostblock',
        'faculty_ghost_grid': faculty_ghost_grid,
        'batch_ghost_grid': batch_ghost_grid
    }
