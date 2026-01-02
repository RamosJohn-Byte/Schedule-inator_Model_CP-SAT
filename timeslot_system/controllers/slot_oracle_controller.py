"""
Slot Oracle Controller - Explicit Slot Coverage Detection

This controller implements a slot-querying mechanism where each slot asks meetings "Do you cover me?"

Concept:
    - Each slot queries all possible meetings for coverage
    - Coverage detection: slot overlaps with [meeting_start, meeting_end)
    - time_slot[i] = OR(meeting1_covers[i], meeting2_covers[i], ...)
    
Advantages:
    - No ghost intervals needed (simpler model)
    - Direct causality (easier to debug)
    - Works well with external meetings
    
Disadvantages:
    - More reification variables (coverage booleans for each slot-meeting pair)
    - No conservation law (solver could cheat without NoOverlap)
"""

def apply_slot_oracle_controller(model, timeslot_data, faculty, batches, 
                                     meetings, faculty_qualified_subjects,
                                     is_assigned_faculty_map, is_assigned_batch_map,
                                     active_for_faculty_map, active_for_batch_map):
    """
    Link meeting intervals directly to time_slot arrays via coverage detection.
    
    Args:
        model: CP-SAT model instance
        timeslot_data: Dictionary from timeslot_grid.create_timeslot_grid_data()
        faculty: List of Faculty objects
        batches: List of Batch objects
        meetings: Dict of (sub_id, s, d_idx) -> meeting dict with start/end/is_active
        faculty_qualified_subjects: Dict of f_idx -> list of Subject objects
        is_assigned_faculty_map: Dict of (f_idx, sub_id, s) -> BoolVar
        is_assigned_batch_map: Dict of (b_idx, sub_id, s) -> BoolVar
        active_for_faculty_map: Dict of (f_idx, sub_id, s, d_idx) -> BoolVar
        active_for_batch_map: Dict of (b_idx, sub_id, s, d_idx) -> BoolVar
    
    Returns:
        Dictionary containing:
            - 'faculty_slot_grid': {(f_idx, day_idx) -> list of slot dicts}
            - 'batch_slot_grid': {(b_idx, day_idx) -> list of slot dicts}
    """
    
    config = timeslot_data['config']
    constants = timeslot_data['constants']
    
    TIME_GRANULARITY = constants['TIME_GRANULARITY']
    MINUTES_IN_A_DAY = constants['MINUTES_IN_A_DAY']
    calculate_slots_for_day = constants['calculate_slots_for_day']
    
    print("\n[Direct Interval Controller] Creating slot grids...")
    
    # ============================================================================
    # STEP 1: Create empty slot grids with time_slot BoolVars
    # ============================================================================
    
    faculty_slot_grid = {}
    batch_slot_grid = {}
    
    # Create slot structure for faculty
    for f_idx, fac in enumerate(faculty):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            num_slots = calculate_slots_for_day(day_idx, config)
            day_offset = day_idx * MINUTES_IN_A_DAY
            day_start_abs = config["DAY_START_MINUTES"] + day_offset
            
            slots = []
            for slot_idx in range(num_slots):
                slot_start = day_start_abs + (slot_idx * TIME_GRANULARITY)
                slot_end = slot_start + TIME_GRANULARITY
                
                # Create time_slot BoolVar (will be set by OR aggregation later)
                time_slot = model.NewBoolVar(f"timeslot_f{f_idx}_d{day_idx}_s{slot_idx}")
                
                slots.append({
                    "slot_idx": slot_idx,
                    "time_slot": time_slot,      # The variable we want to SET
                    "start_abs": slot_start,     # For overlap detection
                    "end_abs": slot_end,
                    "covering_meetings": []      # Will collect coverage booleans
                })
            
            faculty_slot_grid[(f_idx, day_idx)] = slots
    
    # Same for batches - pre-mark external meeting slots
    for b_idx, batch in enumerate(batches):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            num_slots = calculate_slots_for_day(day_idx, config)
            day_offset = day_idx * MINUTES_IN_A_DAY
            day_start_abs = config["DAY_START_MINUTES"] + day_offset
            
            # Pre-compute which slots are covered by external meetings
            external_covered_slots = set()
            for ext_meeting in batch.external_meetings:
                if ext_meeting.day_index == day_idx:
                    ext_start = ext_meeting.start_minutes + day_offset
                    ext_end = ext_meeting.end_minutes + day_offset
                    
                    # Find all slots overlapping this external meeting
                    for slot_idx in range(num_slots):
                        slot_start = day_start_abs + (slot_idx * TIME_GRANULARITY)
                        slot_end = slot_start + TIME_GRANULARITY
                        
                        if ext_start < slot_end and ext_end > slot_start:
                            external_covered_slots.add(slot_idx)
            
            slots = []
            for slot_idx in range(num_slots):
                slot_start = day_start_abs + (slot_idx * TIME_GRANULARITY)
                slot_end = slot_start + TIME_GRANULARITY
                
                # If covered by external meeting, create a BoolVar fixed to 1
                is_external = slot_idx in external_covered_slots
                if is_external:
                    # Must use BoolVar (not Constant) because streak_tracker uses .Not()
                    time_slot = model.NewBoolVar(f"timeslot_b{b_idx}_d{day_idx}_s{slot_idx}_ext")
                    model.Add(time_slot == 1)  # Force to always be occupied
                else:
                    time_slot = model.NewBoolVar(f"timeslot_b{b_idx}_d{day_idx}_s{slot_idx}")
                
                slots.append({
                    "slot_idx": slot_idx,
                    "time_slot": time_slot,
                    "start_abs": slot_start,
                    "end_abs": slot_end,
                    "covering_meetings": [],
                    "is_external": is_external
                })
            
            batch_slot_grid[(b_idx, day_idx)] = slots
    
    print(f"   Created {len(faculty_slot_grid)} faculty grids, {len(batch_slot_grid)} batch grids")
    
    # ============================================================================
    # STEP 2: For each FACULTY meeting, detect which slots it covers
    # ============================================================================
    
    print("[Direct Interval Controller] Linking faculty meetings to slots...")
    
    total_faculty_coverage_vars = 0
    
    for f_idx, fac in enumerate(faculty):
        qualified_subjects = faculty_qualified_subjects.get(f_idx, [])
        
        for sub in qualified_subjects:
            for s in range(sub.ideal_num_sections):
                # Check if faculty assigned to this section
                if (f_idx, sub.subject_id, s) not in is_assigned_faculty_map:
                    continue
                
                # For each day
                for day_idx in range(len(config["SCHEDULING_DAYS"])):
                    # Check if this meeting is active for this faculty
                    active_key = (f_idx, sub.subject_id, s, day_idx)
                    if active_key not in active_for_faculty_map:
                        continue
                    
                    active_for_faculty = active_for_faculty_map[active_key]
                    meeting = meetings[(sub.subject_id, s, day_idx)]
                    
                    meeting_start = meeting["start"]  # IntVar
                    meeting_end = meeting["end"]      # IntVar
                    
                    # Get slots for this faculty-day
                    slots = faculty_slot_grid[(f_idx, day_idx)]
                    
                    # For each slot, detect if meeting covers it
                    for slot in slots:
                        slot_start = slot["start_abs"]  # Constant
                        slot_end = slot["end_abs"]      # Constant
                        
                        # --- COVERAGE DETECTION LOGIC ---
                        # Meeting covers slot if:
                        # 1. Meeting is active for this faculty
                        # 2. Intervals overlap: meeting_start < slot_end AND meeting_end > slot_start
                        
                        # Create helper booleans for overlap conditions
                        starts_before_slot_ends = model.NewBoolVar(
                            f"start_before_f{f_idx}_{sub.subject_id}_s{s}_d{day_idx}_slot{slot['slot_idx']}"
                        )
                        model.Add(meeting_start < slot_end).OnlyEnforceIf(starts_before_slot_ends)
                        model.Add(meeting_start >= slot_end).OnlyEnforceIf(starts_before_slot_ends.Not())
                        
                        ends_after_slot_starts = model.NewBoolVar(
                            f"end_after_f{f_idx}_{sub.subject_id}_s{s}_d{day_idx}_slot{slot['slot_idx']}"
                        )
                        model.Add(meeting_end > slot_start).OnlyEnforceIf(ends_after_slot_starts)
                        model.Add(meeting_end <= slot_start).OnlyEnforceIf(ends_after_slot_starts.Not())
                        
                        # Coverage = active AND starts_before AND ends_after
                        meeting_covers_slot = model.NewBoolVar(
                            f"covers_f{f_idx}_{sub.subject_id}_s{s}_d{day_idx}_slot{slot['slot_idx']}"
                        )
                        model.AddBoolAnd([
                            active_for_faculty, 
                            starts_before_slot_ends, 
                            ends_after_slot_starts
                        ]).OnlyEnforceIf(meeting_covers_slot)
                        model.AddBoolOr([
                            active_for_faculty.Not(),
                            starts_before_slot_ends.Not(),
                            ends_after_slot_starts.Not()
                        ]).OnlyEnforceIf(meeting_covers_slot.Not())
                        
                        # Store this coverage boolean for later aggregation
                        slot["covering_meetings"].append(meeting_covers_slot)
                        total_faculty_coverage_vars += 3  # starts_before, ends_after, covers
    
    print(f"   Faculty coverage variables: ~{total_faculty_coverage_vars:,}")
    
    # ============================================================================
    # STEP 3: For each BATCH meeting, detect which slots it covers
    # ============================================================================
    
    print("[Direct Interval Controller] Linking batch meetings to slots...")
    
    total_batch_coverage_vars = 0
    
    for b_idx, batch in enumerate(batches):
        for sub in batch.subjects:
            for s in range(sub.ideal_num_sections):
                # Check if batch assigned to this section
                if (b_idx, sub.subject_id, s) not in is_assigned_batch_map:
                    continue
                
                # For each day
                for day_idx in range(len(config["SCHEDULING_DAYS"])):
                    active_key = (b_idx, sub.subject_id, s, day_idx)
                    if active_key not in active_for_batch_map:
                        continue
                    
                    active_for_batch = active_for_batch_map[active_key]
                    meeting = meetings[(sub.subject_id, s, day_idx)]
                    
                    meeting_start = meeting["start"]
                    meeting_end = meeting["end"]
                    
                    slots = batch_slot_grid[(b_idx, day_idx)]
                    
                    for slot in slots:
                        # Skip coverage detection for external meeting slots
                        if slot.get("is_external", False):
                            continue
                        
                        slot_start = slot["start_abs"]
                        slot_end = slot["end_abs"]
                        
                        # Same coverage detection logic as faculty
                        starts_before_slot_ends = model.NewBoolVar(
                            f"start_before_b{b_idx}_{sub.subject_id}_s{s}_d{day_idx}_slot{slot['slot_idx']}"
                        )
                        model.Add(meeting_start < slot_end).OnlyEnforceIf(starts_before_slot_ends)
                        model.Add(meeting_start >= slot_end).OnlyEnforceIf(starts_before_slot_ends.Not())
                        
                        ends_after_slot_starts = model.NewBoolVar(
                            f"end_after_b{b_idx}_{sub.subject_id}_s{s}_d{day_idx}_slot{slot['slot_idx']}"
                        )
                        model.Add(meeting_end > slot_start).OnlyEnforceIf(ends_after_slot_starts)
                        model.Add(meeting_end <= slot_start).OnlyEnforceIf(ends_after_slot_starts.Not())
                        
                        meeting_covers_slot = model.NewBoolVar(
                            f"covers_b{b_idx}_{sub.subject_id}_s{s}_d{day_idx}_slot{slot['slot_idx']}"
                        )
                        model.AddBoolAnd([
                            active_for_batch,
                            starts_before_slot_ends,
                            ends_after_slot_starts
                        ]).OnlyEnforceIf(meeting_covers_slot)
                        model.AddBoolOr([
                            active_for_batch.Not(),
                            starts_before_slot_ends.Not(),
                            ends_after_slot_starts.Not()
                        ]).OnlyEnforceIf(meeting_covers_slot.Not())
                        
                        slot["covering_meetings"].append(meeting_covers_slot)
                        total_batch_coverage_vars += 3
    
    print(f"   Batch coverage variables: ~{total_batch_coverage_vars:,}")
    
    # ============================================================================
    # STEP 4: OR AGGREGATION - Set time_slot[i] = OR(all coverage booleans)
    # ============================================================================
    
    print("[Direct Interval Controller] Aggregating coverage with OR logic...")
    
    total_or_constraints = 0
    
    # Faculty aggregation
    for f_idx, fac in enumerate(faculty):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = faculty_slot_grid[(f_idx, day_idx)]
            
            for slot in slots:
                covering_meetings = slot["covering_meetings"]
                time_slot = slot["time_slot"]
                
                if len(covering_meetings) == 0:
                    # No meetings possible for this slot → always vacant
                    model.Add(time_slot == 0)
                elif len(covering_meetings) == 1:
                    # Only one meeting → direct assignment
                    model.Add(time_slot == covering_meetings[0])
                else:
                    # Multiple meetings → OR aggregation
                    # time_slot = True if ANY meeting covers this slot
                    model.AddMaxEquality(time_slot, covering_meetings)
                
                total_or_constraints += 1
    
    # Batch aggregation
    for b_idx, batch in enumerate(batches):
        for day_idx in range(len(config["SCHEDULING_DAYS"])):
            slots = batch_slot_grid[(b_idx, day_idx)]
            
            for slot in slots:
                # Skip external slots - already constrained to 1
                if slot.get("is_external", False):
                    continue
                    
                covering_meetings = slot["covering_meetings"]
                time_slot = slot["time_slot"]
                
                if len(covering_meetings) == 0:
                    model.Add(time_slot == 0)
                elif len(covering_meetings) == 1:
                    model.Add(time_slot == covering_meetings[0])
                else:
                    model.AddMaxEquality(time_slot, covering_meetings)
                
                total_or_constraints += 1
    
    print(f"   OR aggregation constraints: {total_or_constraints:,}")
    
    print(f"[Slot Oracle Controller] Complete:")
    print(f"   Total coverage variables: ~{total_faculty_coverage_vars + total_batch_coverage_vars:,}")
    print(f"   Total time_slot variables: {total_or_constraints:,}")
    
    # Store in timeslot_data for downstream consumers
    timeslot_data['faculty_data'] = faculty_slot_grid
    timeslot_data['batch_data'] = batch_slot_grid
    
    return {
        'controller_type': 'slot_oracle',
        'faculty_ghost_grid': faculty_slot_grid,
        'batch_ghost_grid': batch_slot_grid
    }
