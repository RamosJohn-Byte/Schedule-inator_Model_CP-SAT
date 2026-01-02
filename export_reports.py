# export_reports.py
"""
Report generation functions for analyzing and exporting schedule violations.
Includes human-readable violation reports and raw Excel exports.
"""

import collections
import pandas as pd


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
                print(f"\nStructural violations saved to: {structural_filename}")
            except Exception as e:
                print(f"\nError saving structural violations: {e}")
        else:
            print("\nNo structural violation data to save.")
        
        if soft_excel_data:
            try:
                with pd.ExcelWriter(soft_filename, engine='openpyxl') as writer:
                    for v_type, records in sorted(soft_excel_data.items()):
                        df = pd.DataFrame(records)
                        safe_sheet_name = v_type.replace('_', ' ').title()[:31]
                        df.to_excel(writer, sheet_name=safe_sheet_name, index=False)
                print(f"Soft constraint penalties saved to: {soft_filename}")
            except Exception as e:
                print(f"\nError saving soft constraint penalties: {e}")
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


def generate_violation_report(solver, results, config, faculty, rooms, batches, subjects_map, output_file="violation_report.txt"):
    """
    Generates a human-readable violation report and writes it to a text file.
    
    Args:
        solver: The CP-SAT solver with solution
        results: Dictionary containing violations from run_scheduler()
        config: Configuration dictionary
        faculty: List of Faculty objects
        rooms: List of Room objects
        batches: List of Batch objects
        subjects_map: Dictionary mapping subject_id to Subject objects
        output_file: Output filename (default: "violation_report.txt")
    
    Returns:
        tuple: (section_totals dict, grand_total int)
    """
    
    SLOT_SIZE = 10  # minutes per slot
    
    # Calculate slot thresholds from config
    MAX_CLASS_SLOTS = int(config["MAX_CONTINUOUS_CLASS_HOURS"] * 60 / SLOT_SIZE)
    MAX_GAP_SLOTS = int(config["MAX_GAP_HOURS"] * 60 / SLOT_SIZE)
    MIN_GAP_SLOTS = int(config["MIN_GAP_HOURS"] * 60 / SLOT_SIZE)
    
    # Helper functions
    def format_time_duration(minutes):
        """Convert minutes to 'X hrs Y mins' format without decimals"""
        if minutes == 0:
            return "0 mins"
        
        hours = minutes // 60
        mins = minutes % 60
        
        parts = []
        if hours > 0:
            parts.append(f"{hours} hr" if hours == 1 else f"{hours} hrs")
        if mins > 0:
            parts.append(f"{mins} mins")
        
        return " ".join(parts) if parts else "0 mins"
    
    def slot_to_time(slot_idx, day_start_minutes):
        """Convert slot index to time string (HH:MM AM/PM)"""
        total_minutes = day_start_minutes + (slot_idx * SLOT_SIZE)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        
        period = "AM" if hours < 12 else "PM"
        display_hour = hours if hours <= 12 else hours - 12
        if display_hour == 0:
            display_hour = 12
        
        return f"{display_hour}:{minutes:02d} {period}"
    
    def find_consecutive_ranges(slot_list):
        """Group consecutive slot indices into ranges"""
        if not slot_list:
            return []
        
        sorted_slots = sorted(slot_list)
        ranges = []
        start = sorted_slots[0]
        end = sorted_slots[0]
        
        for i in range(1, len(sorted_slots)):
            if sorted_slots[i] == end + 1:
                end = sorted_slots[i]
            else:
                ranges.append((start, end))
                start = sorted_slots[i]
                end = sorted_slots[i]
        
        ranges.append((start, end))
        return ranges
    
    def get_violation_slots(violation_list, solver):
        """Extract slot indices that have violations from a list of BoolVars/IntVars"""
        slots = []
        for slot_idx, var in enumerate(violation_list):
            if solver.Value(var) > 0:
                slots.append(slot_idx)
        return slots
    
    # Tracking for totals
    section_totals = {}
    grand_total = 0
    
    # Get dummy indices for structural violation reporting
    DUMMY_FACULTY_IDX = results.get("DUMMY_FACULTY_IDX")
    DUMMY_ROOM_IDX = results.get("DUMMY_ROOM_IDX")
    
    # Get section_has_batch to filter unused sections from violation report
    # Unused sections are expected to have dummy resources - not real violations
    section_has_batch = results.get("section_has_batch", {})
    
    # Open file for writing
    with open(output_file, 'w', encoding='utf-8') as f:
        
        # ============================================================
        # 0. STRUCTURAL VIOLATIONS (HARD CONSTRAINT RELAXATIONS)
        # ============================================================
        f.write("=" * 60 + "\n")
        f.write("STRUCTURAL VIOLATIONS (UNASSIGNED RESOURCES)\n")
        f.write("=" * 60 + "\n")
        f.write("These are hard constraints that could not be satisfied.\n")
        f.write("The solver relaxed them to find a feasible solution.\n")
        f.write("=" * 60 + "\n\n")
        
        structural_count = 0
        
        # Collect all structural violations per (subject_id, section_idx)
        # Format: Subject/Section: Teacher Assigned/Unassigned | Room Assigned/Unassigned | X mins missing (Y < Z required)
        section_violations = {}  # key: (subject_id, section_idx) -> dict with teacher, rooms, duration info
        
        # 0a. Gather Faculty info
        if "is_dummy_faculty" in results["violations"]:
            for (subject_id, section_idx), var in results["violations"]["is_dummy_faculty"].items():
                key = (subject_id, section_idx)
                if key in section_has_batch and solver.Value(section_has_batch[key]) == 0:
                    continue
                if key not in section_violations:
                    section_violations[key] = {"teacher": None, "rooms": [], "duration": None}
                
                if solver.Value(var) > 0:
                    section_violations[key]["teacher"] = "Teacher Unassigned"
                else:
                    # Get assigned faculty name
                    faculty_idx = solver.Value(results["assigned_faculty"][key])
                    if 0 <= faculty_idx < len(faculty):
                        section_violations[key]["teacher"] = f"{faculty[faculty_idx].name} Assigned"
                    else:
                        section_violations[key]["teacher"] = "Teacher Unassigned"
        
        # 0b. Gather Room info (room is now per section, not per day)
        if "is_dummy_room" in results["violations"]:
            for (subject_id, section_idx), var in results["violations"]["is_dummy_room"].items():
                key = (subject_id, section_idx)
                if key in section_has_batch and solver.Value(section_has_batch[key]) == 0:
                    continue
                if key not in section_violations:
                    section_violations[key] = {"teacher": None, "rooms": [], "duration": None}
                
                if solver.Value(var) > 0:
                    section_violations[key]["rooms"].append("Room Unassigned")
                else:
                    # Get assigned room code (same for all days)
                    room_idx = solver.Value(results["assigned_room"][(subject_id, section_idx)])
                    if 0 <= room_idx < len(rooms):
                        section_violations[key]["rooms"].append(f"{rooms[room_idx].room_id}")
                    else:
                        section_violations[key]["rooms"].append("Room Unassigned")
        
        # 0c. Gather Duration info
        if "duration_violations" in results["violations"]:
            for (subject_id, section_idx), var in results["violations"]["duration_violations"].items():
                key = (subject_id, section_idx)
                if key in section_has_batch and solver.Value(section_has_batch[key]) == 0:
                    continue
                if key not in section_violations:
                    section_violations[key] = {"teacher": None, "rooms": [], "duration": None}
                
                if solver.Value(var) > 0:
                    subject = subjects_map.get(subject_id)
                    required_mins = subject.required_weekly_minutes if subject else 0
                    # Calculate actual scheduled minutes
                    actual_mins = 0
                    for d_idx in range(len(config["SCHEDULING_DAYS"])):
                        meeting_key = (subject_id, section_idx, d_idx)
                        if meeting_key in results["meetings"]:
                            meeting = results["meetings"][meeting_key]
                            if solver.Value(meeting["is_active"]):
                                actual_mins += solver.Value(meeting["duration"])
                    missing_mins = required_mins - actual_mins
                    section_violations[key]["duration"] = (missing_mins, actual_mins, required_mins)
        
        # Now output consolidated violations with uniform column widths
        violation_lines = []
        
        # First pass: collect all violations and determine max widths
        violation_data = []
        for (subject_id, section_idx), info in sorted(section_violations.items()):
            has_teacher_violation = info["teacher"] == "Teacher Unassigned"
            has_room_violation = any("Unassigned" in r for r in info["rooms"])
            has_duration_violation = info["duration"] is not None
            
            if not (has_teacher_violation or has_room_violation or has_duration_violation):
                continue
            
            subject = subjects_map.get(subject_id)
            subject_name = subject.subject_id if subject else subject_id
            
            # Subject/Section column
            col1 = f"{subject_name}/Section {section_idx + 1}"
            
            # Teacher column - just show status
            if has_teacher_violation:
                col2 = "Teacher Unassigned"
            elif info["teacher"]:
                # Extract just the name (remove " Assigned" suffix)
                col2 = info["teacher"]
            else:
                col2 = "-"
            
            # Room column - show all day:room assignments
            if info["rooms"]:
                col3 = ", ".join(info["rooms"])
            else:
                col3 = "-"
            
            # Duration column
            if has_duration_violation:
                missing, actual, required = info["duration"]
                col4 = f"{missing} mins missing ({actual} mins < {required} required mins)"
            else:
                col4 = "-"
            
            violation_data.append((col1, col2, col3, col4))
        
        if violation_data:
            # Calculate max widths for alignment
            max_col1 = max(len(row[0]) for row in violation_data)
            max_col2 = max(len(row[1]) for row in violation_data)
            max_col3 = max(len(row[2]) for row in violation_data)
            
            # Build formatted lines
            for col1, col2, col3, col4 in violation_data:
                line = f"  {col1:<{max_col1}} | {col2:<{max_col2}} | {col3:<{max_col3}} | {col4}"
                violation_lines.append(line)
                structural_count += 1
        
        if violation_lines:
            f.write("STRUCTURAL VIOLATIONS:\n")
            f.write("-" * 100 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write("\n")
        
        # 0d. Day Gaps (now structural)
        day_gap_count = 0
        if "faculty_day_gaps" in results["violations"]:
            for f_idx, flag_list in results["violations"]["faculty_day_gaps"].items():
                for day_offset, var in enumerate(flag_list):
                    if hasattr(var, 'Proto') and solver.Value(var) > 0:
                        day_gap_count += 1
                        structural_count += 1
        
        if "batch_day_gaps" in results["violations"]:
            for b_idx, flag_list in results["violations"]["batch_day_gaps"].items():
                for day_offset, var in enumerate(flag_list):
                    if hasattr(var, 'Proto') and solver.Value(var) > 0:
                        day_gap_count += 1
                        structural_count += 1
        
        if day_gap_count > 0:
            f.write(f"DAY GAPS: {day_gap_count} idle days between teaching days\n")
            f.write("-" * 40 + "\n\n")
        
        if structural_count == 0:
            f.write("No structural violations - all hard constraints satisfied!\n\n")
        else:
            f.write(f"\nTotal Structural Violations: {structural_count}\n")
        
        f.write("=" * 60 + "\n\n\n")
        
        # ============================================================
        # FACULTY WORKLOAD SUMMARY
        # ============================================================
        f.write("=" * 60 + "\n")
        f.write("FACULTY WORKLOAD SUMMARY\n")
        f.write("=" * 60 + "\n\n")
        
        # Calculate actual hours worked for each faculty
        faculty_workload = []
        for f_idx, fac in enumerate(faculty):
            total_mins = 0
            sections_taught = []
            
            # Go through all subjects this faculty is qualified for
            for subject_id in fac.qualified_subject_ids:
                if subject_id not in subjects_map:
                    continue
                subject = subjects_map[subject_id]
                
                for s in range(subject.ideal_num_sections):
                    key = (subject_id, s)
                    if key not in results["assigned_faculty"]:
                        continue
                    
                    # Check if this faculty is assigned to this section
                    assigned_fac_idx = solver.Value(results["assigned_faculty"][key])
                    if assigned_fac_idx != f_idx:
                        continue
                    
                    # Check if section has batch (is used)
                    if key in section_has_batch and solver.Value(section_has_batch[key]) == 0:
                        continue
                    
                    # Sum up duration from all active meetings
                    section_mins = 0
                    for d_idx in range(len(config["SCHEDULING_DAYS"])):
                        mtg_key = (subject_id, s, d_idx)
                        if mtg_key in results["meetings"]:
                            mtg = results["meetings"][mtg_key]
                            if solver.Value(mtg["is_active"]):
                                section_mins += solver.Value(mtg["duration"])
                    
                    if section_mins > 0:
                        sections_taught.append(f"{subject_id}/s{s+1}({section_mins}min)")
                        total_mins += section_mins
            
            max_mins = fac.max_hours * 60
            min_mins = fac.min_hours * 60
            
            # Determine status
            if total_mins > max_mins:
                status = "OVER MAX"
            elif total_mins < min_mins and min_mins > 0:
                status = "UNDER MIN"
            else:
                status = "OK"
            
            faculty_workload.append({
                "name": fac.name,
                "total_mins": total_mins,
                "max_mins": max_mins,
                "min_mins": min_mins,
                "status": status,
                "sections": sections_taught
            })
        
        # Sort by total minutes (descending)
        faculty_workload.sort(key=lambda x: x["total_mins"], reverse=True)
        
        # Calculate max name width for alignment
        max_name_len = max(len(fw["name"]) for fw in faculty_workload) if faculty_workload else 10
        
        for fw in faculty_workload:
            hours_worked = fw["total_mins"] / 60
            max_hours = fw["max_mins"] / 60
            min_hours = fw["min_mins"] / 60
            
            line = f"  {fw['name']:<{max_name_len}} | {fw['total_mins']:>4} mins ({hours_worked:>5.1f}h) / {fw['min_mins']:>4} mins ({min_hours:>4.1f}h min) - {fw['max_mins']:>4} mins ({max_hours:>4.1f}h max) | {fw['status']}"
            f.write(line + "\n")
            
            # Optionally show sections taught (if any)
            if fw["sections"]:
                sections_str = ", ".join(fw["sections"])
                f.write(f"    └─ Sections: {sections_str}\n")
        
        f.write("\n" + "=" * 60 + "\n\n\n")
        
        # ============================================================
        # 1. FACULTY OVERLOAD VIOLATIONS
        # ============================================================
        violation_lines = []
        section_penalty = 0
        
        if "faculty_overload" in results["violations"]:
            for f_idx, var in enumerate(results["violations"]["faculty_overload"]):
                excess_mins = solver.Value(var)
                if excess_mins > 0:
                    faculty_obj = faculty[f_idx]
                    actual_total_mins = faculty_obj.max_hours * 60 + excess_mins
                    max_hours = faculty_obj.max_hours
                    
                    penalty = excess_mins * config["ConstraintPenalties"]["FACULTY_OVERLOAD_PER_MINUTE"]
                    section_penalty += penalty
                    
                    line = f"OVERLOAD {faculty_obj.name} by {format_time_duration(excess_mins)} " \
                           f"({format_time_duration(actual_total_mins)} > {max_hours} hrs) [Penalty: {penalty}]"
                    violation_lines.append(line)
        
        if violation_lines:
            f.write("FACULTY OVERLOAD VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal OVERLOAD Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["OVERLOAD"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # 2. SECTION OVERFILL VIOLATIONS
        # ============================================================
        violation_lines = []
        section_penalty = 0
        
        if "section_overfill" in results["violations"]:
            for (subject_id, section_idx), var in results["violations"]["section_overfill"].items():
                excess_students = solver.Value(var)
                if excess_students > 0:
                    # Determine max students based on subject type
                    subject = subjects_map[subject_id]
                    if "GE-" in subject_id or "PE" in subject_id:
                        max_students = config["MAX_STUDENTS_GENED"]
                    else:
                        max_students = config["MAX_STUDENTS_CCISM"]
                    
                    actual_students = max_students + excess_students
                    penalty = excess_students * config["ConstraintPenalties"]["SECTION_OVERFILL_PER_STUDENT"]
                    section_penalty += penalty
                    
                    line = f"OVERFILL {subject_id} Sec {section_idx + 1} by {excess_students} students " \
                           f"({actual_students} > {max_students}) [Penalty: {penalty}]"
                    violation_lines.append(line)
        
        if violation_lines:
            f.write("SECTION OVERFILL VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal OVERFILL Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["OVERFILL"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # 3. SECTION UNDERFILL VIOLATIONS (GenEd only)
        # ============================================================
        violation_lines = []
        section_penalty = 0
        
        if "section_underfill" in results["violations"]:
            for (subject_id, section_idx), var in results["violations"]["section_underfill"].items():
                deficit_students = solver.Value(var)
                if deficit_students > 0:
                    min_students = config["MIN_STUDENTS_GENED"]
                    actual_students = min_students - deficit_students
                    penalty = deficit_students * config["ConstraintPenalties"]["GENED_UNDER_MINIMUM_PER_STUDENT"]
                    section_penalty += penalty
                    
                    line = f"UNDERFILL {subject_id} Sec {section_idx + 1} by {deficit_students} students " \
                           f"({actual_students} < {min_students}) [Penalty: {penalty}]"
                    violation_lines.append(line)
        
        if violation_lines:
            f.write("SECTION UNDERFILL VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal UNDERFILL Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["UNDERFILL"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # 4. EXCESS CONTINUOUS CLASS VIOLATIONS (Faculty + Batch)
        # ============================================================
        violation_lines = []
        section_penalty = 0
        
        # Batch excess class - REMOVED (unused tracker - never populated)
        # if "batch_excess_continuous_class" in results["violations"]:
        
        if violation_lines:
            f.write("EXCESS CONTINUOUS CLASS VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal EXCESS-CLASS Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["EXCESS-CLASS"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # 5. SHORT GAP VIOLATIONS (Faculty + Batch)
        # ============================================================
        violation_lines = []
        section_penalty = 0
        
        # Batch short gaps - REMOVED (unused tracker - never populated)
        # if "batch_underfill_gaps" in results["violations"]:
        
        if violation_lines:
            f.write("SHORT GAP VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal SHORT-GAP Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["SHORT-GAP"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # 6. LONG GAP VIOLATIONS (Faculty + Batch)
        # ============================================================
        violation_lines = []
        section_penalty = 0
        
        # Faculty long gaps
        if "faculty_excess_gaps" in results["violations"]:
            for f_idx in results["violations"]["faculty_excess_gaps"]:
                for day_idx in results["violations"]["faculty_excess_gaps"][f_idx]:
                    violation_list = results["violations"]["faculty_excess_gaps"][f_idx][day_idx]
                    
                    # Build list of (slot_idx, excess_slots) for violations
                    violations = []
                    for slot_idx, var in enumerate(violation_list):
                        excess_slots = solver.Value(var)
                        if excess_slots > 0:
                            violations.append((slot_idx, excess_slots))
                    
                    # Process each violation (gap ends at this slot)
                    for slot_idx, excess_slots in violations:
                        # Gap ends at slot_idx (class starts here)
                        # Total gap = MAX_GAP_SLOTS + excess_slots
                        # VIOLATION RANGE = only the excess portion (beyond acceptable gap)
                        violation_start_slot = slot_idx - excess_slots
                        violation_end_slot = slot_idx  # Class starts here
                        
                        start_time = slot_to_time(violation_start_slot, config["DAY_START_MINUTES"])
                        end_time = slot_to_time(violation_end_slot, config["DAY_START_MINUTES"])
                        
                        excess_mins = excess_slots * SLOT_SIZE
                        total_gap_slots = MAX_GAP_SLOTS + excess_slots
                        actual_gap = total_gap_slots * SLOT_SIZE
                        max_gap = MAX_GAP_SLOTS * SLOT_SIZE
                        
                        # Convert per-hour penalty to per-slot (matching solver logic)
                        slots_per_hour = 60 / config["TIME_GRANULARITY_MINUTES"]
                        penalty_per_slot = int(config["ConstraintPenalties"]["EXCESS_GAP_PER_HOUR"] / slots_per_hour)
                        penalty = excess_slots * penalty_per_slot
                        section_penalty += penalty
                        
                        day_name = config["SCHEDULING_DAYS"][day_idx][:3].capitalize()
                        faculty_name = faculty[f_idx].name
                        
                        line = f"LONG-GAP {faculty_name} ({day_name} {start_time} - {end_time}) " \
                               f"by {format_time_duration(excess_mins)} " \
                               f"({format_time_duration(actual_gap)} > {format_time_duration(max_gap)}) " \
                               f"[Penalty: {penalty}]"
                        violation_lines.append(line)
        
        # Batch long gaps
        if "batch_excess_gaps" in results["violations"]:
            for b_idx in results["violations"]["batch_excess_gaps"]:
                for day_idx in results["violations"]["batch_excess_gaps"][b_idx]:
                    violation_list = results["violations"]["batch_excess_gaps"][b_idx][day_idx]
                    
                    # Build list of (slot_idx, excess_slots) for violations
                    violations = []
                    for slot_idx, var in enumerate(violation_list):
                        excess_slots = solver.Value(var)
                        if excess_slots > 0:
                            violations.append((slot_idx, excess_slots))
                    
                    # Process each violation (gap ends at this slot)
                    for slot_idx, excess_slots in violations:
                        # Gap ends at slot_idx (class starts here)
                        # Total gap = MAX_GAP_SLOTS + excess_slots
                        # VIOLATION RANGE = only the excess portion (beyond acceptable gap)
                        violation_start_slot = slot_idx - excess_slots
                        violation_end_slot = slot_idx  # Class starts here
                        
                        start_time = slot_to_time(violation_start_slot, config["DAY_START_MINUTES"])
                        end_time = slot_to_time(violation_end_slot, config["DAY_START_MINUTES"])
                        
                        excess_mins = excess_slots * SLOT_SIZE
                        total_gap_slots = MAX_GAP_SLOTS + excess_slots
                        actual_gap = total_gap_slots * SLOT_SIZE
                        max_gap = MAX_GAP_SLOTS * SLOT_SIZE
                        
                        # Convert per-hour penalty to per-slot (matching solver logic)
                        slots_per_hour = 60 / config["TIME_GRANULARITY_MINUTES"]
                        penalty_per_slot = int(config["ConstraintPenalties"]["EXCESS_GAP_PER_HOUR"] / slots_per_hour)
                        penalty = excess_slots * penalty_per_slot
                        section_penalty += penalty
                        
                        day_name = config["SCHEDULING_DAYS"][day_idx][:3].capitalize()
                        batch_name = batches[b_idx].batch_id
                        
                        line = f"LONG-GAP {batch_name} ({day_name} {start_time} - {end_time}) " \
                               f"by {format_time_duration(excess_mins)} " \
                               f"({format_time_duration(actual_gap)} > {format_time_duration(max_gap)}) " \
                               f"[Penalty: {penalty}]"
                        violation_lines.append(line)
        
        if violation_lines:
            f.write("LONG GAP VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal LONG-GAP Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["LONG-GAP"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # 7. UNDER MINIMUM BLOCK VIOLATIONS (Faculty + Batch)
        # ============================================================
        violation_lines = []
        section_penalty = 0
        MIN_BLOCK_SLOTS = int(config.get("MIN_CONTINUOUS_CLASS_HOURS", 0) * 60 / SLOT_SIZE)
        
        # Faculty under minimum blocks
        if "faculty_under_minimum_block" in results["violations"]:
            for f_idx in results["violations"]["faculty_under_minimum_block"]:
                for day_idx in results["violations"]["faculty_under_minimum_block"][f_idx]:
                    violation_list = results["violations"]["faculty_under_minimum_block"][f_idx][day_idx]
                    
                    # Iterate through violation list where index = slot position
                    for slot_idx, var in enumerate(violation_list):
                        deficiency_slots = solver.Value(var)
                        
                        if deficiency_slots > 0:
                            # Block ends at slot_idx with deficiency
                            actual_block_slots = MIN_BLOCK_SLOTS - deficiency_slots
                            block_start_slot = slot_idx - actual_block_slots + 1
                            block_end_slot = slot_idx + 1  # Exclusive end
                            
                            block_start_time = slot_to_time(block_start_slot, config["DAY_START_MINUTES"])
                            block_end_time = slot_to_time(block_end_slot, config["DAY_START_MINUTES"])
                            
                            deficiency_mins = deficiency_slots * SLOT_SIZE
                            actual_block_mins = actual_block_slots * SLOT_SIZE
                            min_block_mins = MIN_BLOCK_SLOTS * SLOT_SIZE
                            
                            # Convert per-hour penalty to per-slot (matching solver logic)
                            slots_per_hour = 60 / config["TIME_GRANULARITY_MINUTES"]
                            penalty_per_slot = int(config["ConstraintPenalties"]["UNDER_MINIMUM_BLOCK_PER_HOUR"] / slots_per_hour)
                            penalty = deficiency_slots * penalty_per_slot
                            section_penalty += penalty
                            
                            day_name = config["SCHEDULING_DAYS"][day_idx][:3].capitalize()
                            faculty_name = faculty[f_idx].name
                            
                            line = f"UNDER-MIN-BLOCK {faculty_name} ({day_name} {block_start_time} - {block_end_time}) " \
                                   f"short by {format_time_duration(deficiency_mins)} " \
                                   f"({format_time_duration(actual_block_mins)} < {format_time_duration(min_block_mins)}) " \
                                   f"[Penalty: {penalty}]"
                            violation_lines.append(line)
        
        # Batch under minimum blocks
        if "batch_under_minimum_block" in results["violations"]:
            for b_idx in results["violations"]["batch_under_minimum_block"]:
                for day_idx in results["violations"]["batch_under_minimum_block"][b_idx]:
                    violation_list = results["violations"]["batch_under_minimum_block"][b_idx][day_idx]
                    
                    # Iterate through violation list where index = slot position
                    for slot_idx, var in enumerate(violation_list):
                        deficiency_slots = solver.Value(var)
                        
                        if deficiency_slots > 0:
                            # Block ends at slot_idx with deficiency
                            actual_block_slots = MIN_BLOCK_SLOTS - deficiency_slots
                            block_start_slot = slot_idx - actual_block_slots + 1
                            block_end_slot = slot_idx + 1  # Exclusive end
                            
                            block_start_time = slot_to_time(block_start_slot, config["DAY_START_MINUTES"])
                            block_end_time = slot_to_time(block_end_slot, config["DAY_START_MINUTES"])
                            
                            deficiency_mins = deficiency_slots * SLOT_SIZE
                            actual_block_mins = actual_block_slots * SLOT_SIZE
                            min_block_mins = MIN_BLOCK_SLOTS * SLOT_SIZE
                            
                            # Convert per-hour penalty to per-slot (matching solver logic)
                            slots_per_hour = 60 / config["TIME_GRANULARITY_MINUTES"]
                            penalty_per_slot = int(config["ConstraintPenalties"]["UNDER_MINIMUM_BLOCK_PER_HOUR"] / slots_per_hour)
                            penalty = deficiency_slots * penalty_per_slot
                            section_penalty += penalty
                            
                            day_name = config["SCHEDULING_DAYS"][day_idx][:3].capitalize()
                            batch_name = batches[b_idx].batch_id
                            
                            line = f"UNDER-MIN-BLOCK {batch_name} ({day_name} {block_start_time} - {block_end_time}) " \
                                   f"short by {format_time_duration(deficiency_mins)} " \
                                   f"({format_time_duration(actual_block_mins)} < {format_time_duration(min_block_mins)}) " \
                                   f"[Penalty: {penalty}]"
                            violation_lines.append(line)
        
        if violation_lines:
            f.write("UNDER MINIMUM BLOCK VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal UNDER-MIN-BLOCK Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["UNDER-MIN-BLOCK"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # NON-PREFERRED SUBJECT VIOLATIONS
        # ============================================================
        violation_lines = []
        section_penalty = 0
        
        if "faculty_non_preferred_subject" in results["violations"]:
            penalty_weight = config["ConstraintPenalties"]["NON_PREFERRED_SUBJECT_PER_SECTION"]
            
            for f_idx in sorted(results["violations"]["faculty_non_preferred_subject"].keys()):
                faculty_name = faculty[f_idx].name
                subject_data = results["violations"]["faculty_non_preferred_subject"][f_idx]
                
                for sub_id in sorted(subject_data.keys()):
                    section_flags = subject_data[sub_id]
                    
                    # Count how many sections are assigned (sum of true flags)
                    sections_assigned = sum(solver.Value(flag) for flag in section_flags)
                    
                    if sections_assigned > 0:
                        penalty = sections_assigned * penalty_weight
                        section_penalty += penalty
                        
                        line = f"{faculty_name} | Subject: {sub_id} | Sections assigned: {sections_assigned} | Penalty: {sections_assigned} × {penalty_weight} = {penalty}"
                        violation_lines.append(line)
        
        if violation_lines:
            f.write("NON-PREFERRED SUBJECT VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal NON-PREFERRED Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["NON-PREFERRED"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # DAY GAP VIOLATIONS (Faculty & Batch)
        # ============================================================
        violation_lines = []
        section_penalty = 0
        
        # Faculty day gaps
        if "faculty_day_gaps" in results["violations"]:
            penalty_weight = config["ConstraintPenalties"]["DAY_GAP_PENALTY"]
            
            for f_idx in sorted(results["violations"]["faculty_day_gaps"].keys()):
                faculty_name = faculty[f_idx].name
                gap_flags = results["violations"]["faculty_day_gaps"][f_idx]
                
                # Count how many day gaps exist (sum of true flags)
                day_gaps_count = sum(solver.Value(flag) for flag in gap_flags)
                
                if day_gaps_count > 0:
                    penalty = day_gaps_count * penalty_weight
                    section_penalty += penalty
                    
                    # Identify which days are gaps (enumerate starts at 1 for Tue, Wed, Thu)
                    gap_days = []
                    for idx, flag in enumerate(gap_flags, start=1):
                        if solver.Value(flag) > 0:
                            gap_days.append(config["SCHEDULING_DAYS"][idx])
                    
                    gap_days_str = ", ".join(gap_days)
                    line = f"{faculty_name} | Idle days between teaching days: {gap_days_str} | Count: {day_gaps_count} | Penalty: {day_gaps_count} × {penalty_weight} = {penalty}"
                    violation_lines.append(line)
        
        # Batch day gaps
        if "batch_day_gaps" in results["violations"]:
            penalty_weight = config["ConstraintPenalties"]["DAY_GAP_PENALTY"]
            
            for b_idx in sorted(results["violations"]["batch_day_gaps"].keys()):
                batch_name = batches[b_idx].batch_id
                gap_flags = results["violations"]["batch_day_gaps"][b_idx]
                
                # Count how many day gaps exist (sum of true flags)
                day_gaps_count = sum(solver.Value(flag) for flag in gap_flags)
                
                if day_gaps_count > 0:
                    penalty = day_gaps_count * penalty_weight
                    section_penalty += penalty
                    
                    # Identify which days are gaps (enumerate starts at 1 for Tue, Wed, Thu)
                    gap_days = []
                    for idx, flag in enumerate(gap_flags, start=1):
                        if solver.Value(flag) > 0:
                            gap_days.append(config["SCHEDULING_DAYS"][idx])
                    
                    gap_days_str = ", ".join(gap_days)
                    line = f"{batch_name} | Idle days between class days: {gap_days_str} | Count: {day_gaps_count} | Penalty: {day_gaps_count} × {penalty_weight} = {penalty}"
                    violation_lines.append(line)
        
        if violation_lines:
            f.write("DAY GAP VIOLATIONS\n")
            f.write("=" * 40 + "\n")
            for line in violation_lines:
                f.write(line + "\n")
            f.write(f"\nTotal DAY-GAP Penalties: {section_penalty}\n")
            f.write("=" * 40 + "\n\n\n")
            section_totals["DAY-GAP"] = section_penalty
            grand_total += section_penalty
        
        # ============================================================
        # GRAND TOTAL
        # ============================================================
        f.write("=" * 40 + "\n")
        f.write(f"TOTAL PENALTIES FROM ALL VIOLATIONS: {grand_total}\n")
        f.write("=" * 40 + "\n")
    
    print(f"Violation report generated: {output_file}")
    print(f"Total violations penalty: {grand_total}")
    
    return section_totals, grand_total
