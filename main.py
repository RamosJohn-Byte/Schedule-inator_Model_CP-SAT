# main.py
import collections
import os
import gc
import sys
from datetime import datetime
from numpy import ceil
from ortools.sat.python import cp_model
import json
import time
import random
import pandas as pd
from data_models import Program, Room, Faculty, Subject, Batch, BannedTime, TimeBlock, ExternalMeeting, RoomType, SubjectType
from scheduler import run_scheduler
from utils import flush_print, create_output_folder, load_config
from export_db import save_schedule_to_db, save_schedule_with_full_view
from export_reports import print_raw_violations, human_readable_violation_report
from export_debug import export_soft_time_violations_detailed


# NOTE: The following functions have been moved to modular files:
# - flush_print, create_output_folder, load_config -> utils.py
# - save_schedule_to_db, save_schedule_with_full_view -> export_db.py
# - print_raw_violations, human_readable_violation_report -> export_reports.py

def load_data(config, model):
    # Data folder path (change this to switch between data sets)
    DATA_FOLDER = 'data'
    
    # Load lookup tables first
    try:
        df_room_types = pd.read_csv(f'{DATA_FOLDER}/room_types.csv')
        print(f"Successfully loaded {DATA_FOLDER}/room_types.csv")
    except FileNotFoundError:
        print(f"WARNING: {DATA_FOLDER}/room_types.csv not found. Creating empty lookup.")
        df_room_types = pd.DataFrame(columns=['id', 'name', 'description'])
    
    try:
        df_subject_types = pd.read_csv(f'{DATA_FOLDER}/subject_types.csv')
        print(f"Successfully loaded {DATA_FOLDER}/subject_types.csv")
    except FileNotFoundError:
        print(f"WARNING: {DATA_FOLDER}/subject_types.csv not found. Creating empty lookup.")
        df_subject_types = pd.DataFrame(columns=['id', 'name', 'description'])
    
    # Build lookup dictionaries
    room_types_map = {}
    for _, row in df_room_types.iterrows():
        rt = RoomType(
            id=int(row['id']),
            name=row['name'],
            description=row.get('description', None)
        )
        room_types_map[rt.id] = rt
    
    subject_types_map = {}
    for _, row in df_subject_types.iterrows():
        st = SubjectType(
            id=int(row['id']),
            name=row['name'],
            description=row.get('description', None)
        )
        subject_types_map[st.id] = st
    
    print(f"Loaded {len(room_types_map)} room types")
    print(f"Loaded {len(subject_types_map)} subject types")
    
    # Load main entity tables
    df_faculty = pd.read_csv(f'{DATA_FOLDER}/faculty.csv')
    df_rooms = pd.read_csv(f'{DATA_FOLDER}/rooms.csv')
    df_subjects = pd.read_csv(f'{DATA_FOLDER}/subjects.csv')
    df_batches = pd.read_csv(f'{DATA_FOLDER}/student_batches.csv')

    # --- Fail-safe for banned_times.csv ---
    try:
        df_banned_times = pd.read_csv(f'{DATA_FOLDER}/banned_times.csv', dtype={'start_time': str, 'end_time': str})
        print(f"Successfully loaded {DATA_FOLDER}/banned_times.csv")
    except FileNotFoundError:
        print(f"WARNING: {DATA_FOLDER}/banned_times.csv not found. Continuing without banned times.")
        # Create an empty DataFrame with the expected columns
        df_banned_times = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time'])
    except pd.errors.EmptyDataError:
        print(f"WARNING: {DATA_FOLDER}/banned_times.csv is empty. Continuing without banned times.")
        df_banned_times = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time'])
    except Exception as e:
        print(f"ERROR reading {DATA_FOLDER}/banned_times.csv: {e}. Continuing without banned times.")
        df_banned_times = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time'])

    # --- Fail-safe for external_meetings.csv ---
    try:
        df_external_meetings = pd.read_csv(f'{DATA_FOLDER}/external_meetings.csv', dtype={'start_time': str, 'end_time': str})
        print(f"Successfully loaded {DATA_FOLDER}/external_meetings.csv")
    except FileNotFoundError:
        print(f"WARNING: {DATA_FOLDER}/external_meetings.csv not found. Continuing without external meetings.")
        # Create an empty DataFrame with the expected columns
        df_external_meetings = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time', 'event_name', 'description'])
    except pd.errors.EmptyDataError:
        print(f"WARNING: {DATA_FOLDER}/external_meetings.csv is empty. Continuing without external meetings.")
        df_external_meetings = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time', 'event_name', 'description'])
    except Exception as e:
        print(f"ERROR reading {DATA_FOLDER}/external_meetings.csv: {e}. Continuing without external meetings.")
        df_external_meetings = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time', 'event_name', 'description'])

    # --- The rest of your code continues below ---
    # It can now safely use df_banned_times and df_external_meetings, even if they are empty.

    banned_times_by_batch = collections.defaultdict(list)
    external_meetings_by_batch = collections.defaultdict(list)
    day_map = {day: i for i, day in enumerate(config["SCHEDULING_DAYS"])}

    for _, row in df_banned_times.iterrows():
        day_idx = day_map.get(row['day'].upper())
        if day_idx is None:
            continue # Skip if day is invalid

        start_h, start_m = map(int, row['start_time'].split(':'))
        end_h, end_m = map(int, row['end_time'].split(':'))
        
        start_total_min = start_h * 60 + start_m
        end_total_min = end_h * 60 + end_m
        
        start_slot = (start_total_min - config["DAY_START_MINUTES"]) // 10
        end_slot = (end_total_min - config["DAY_START_MINUTES"]) // 10
        
        if start_slot < end_slot:
            banned_times_by_batch[row['batch_id']].append(
                BannedTime(day_index=day_idx, start_slot=start_slot, end_slot=end_slot)
            )

    for _, row in df_external_meetings.iterrows():
        day_idx = day_map.get(row['day'].upper())
        if day_idx is None:
            continue

        start_h, start_m = map(int, row['start_time'].split(':'))
        end_h, end_m = map(int, row['end_time'].split(':'))

        start_total_min = start_h * 60 + start_m
        end_total_min = end_h * 60 + end_m
        
        # Get event_name and description, with defaults if missing
        event_name = row.get('event_name', 'External Meeting')
        description = row.get('description', '')

        if start_total_min < end_total_min:
            external_meetings_by_batch[row['batch_id']].append(
                ExternalMeeting(
                    day_index=day_idx, 
                    start_minutes=start_total_min, 
                    end_minutes=end_total_min,
                    event_name=event_name,
                    description=description
                )
            )

    faculty = []
    for _, row in df_faculty.iterrows():
        # Parse qualified subject IDs (semicolon-delimited integers)
        qualified_ids = set()
        if pd.notna(row.get('qualified_subjects')) and str(row['qualified_subjects']).strip():
            qualified_ids = set(int(sid.strip()) for sid in str(row['qualified_subjects']).split(';') if sid.strip())
        
        # Parse preferred subject IDs (semicolon-delimited integers)
        preferred_ids = set()
        if pd.notna(row.get('preferred_subjects')) and str(row['preferred_subjects']).strip():
            preferred_ids = set(int(sid.strip()) for sid in str(row['preferred_subjects']).split(';') if sid.strip())
        
        # Get max_subjects if present
        max_subjects = int(row['max_subjects']) if pd.notna(row.get('max_subjects')) and row['max_subjects'] > 0 else None
        
        # Get row_id from id column if present
        row_id = int(row['id']) if 'id' in df_faculty.columns and pd.notna(row.get('id')) else None
        
        # Convert load units to hours (multiply by 3)
        max_hours = int(row['max_load']) * 3 if pd.notna(row.get('max_load')) else 0
        min_hours = int(row['min_load']) * 3 if pd.notna(row.get('min_load')) else 0
        
        faculty.append(Faculty(
            id=str(row['faculty_id']),
            name=row['name'],
            max_hours=max_hours,
            min_hours=min_hours,
            qualified_subject_ids=qualified_ids,
            preferred_subject_ids=preferred_ids,
            max_subjects=max_subjects,
            row_id=row_id
        ))
    rooms = []
    for _, row in df_rooms.iterrows():
        row_id = int(row['id']) if 'id' in df_rooms.columns and pd.notna(row.get('id')) else None
        rooms.append(Room(
            room_id=row['room_id'],
            capacity=int(row['capacity']),
            room_type_id=int(row['room_type_id']),
            row_id=row_id
        ))
    
    subjects_map = {}
    for _, row in df_subjects.iterrows():
        subject_id = int(row['id'])
        subject_code = row['subject_code']
        
        req_mins = int((row['lecture_units'] * config['LECTURE_UNIT_TO_HOURS'] + row['lab_units'] * config['LAB_UNIT_TO_HOURS']) * 60)
        
        # Get max_enrollment if present and > 0, otherwise None
        max_enrollment = int(row['max_enrollment']) if pd.notna(row.get('max_enrollment')) and row['max_enrollment'] > 0 else None
        
        # Get min_enrollment if present and > 0, otherwise None
        min_enrollment = int(row['min_enrollment']) if pd.notna(row.get('min_enrollment')) and row['min_enrollment'] > 0 else None
        
        # Get min/max meetings if present and > 0, otherwise None
        min_meetings = int(row['min_meetings']) if pd.notna(row.get('min_meetings')) and row['min_meetings'] >= 0 else None
        max_meetings = int(row['max_meetings']) if pd.notna(row.get('max_meetings')) and row['max_meetings'] >= 0 else None
        
        # Parse integer IDs
        subject_type_id = int(row['subject_type_id']) if pd.notna(row.get('subject_type_id')) else None
        room_type_id = int(row['room_type_id']) if pd.notna(row.get('room_type_id')) else None
        linked_subject_id = int(row['linked_subject_id']) if pd.notna(row.get('linked_subject_id')) else None
        
        # Get row_id from id column if present
        row_id = int(row['id']) if 'id' in df_subjects.columns and pd.notna(row.get('id')) else None
        
        sub = Subject(
            subject_id=subject_id,
            subject_code=subject_code,
            required_weekly_minutes=req_mins,
            subject_type_id=subject_type_id,
            room_type_id=room_type_id,
            linked_subject_id=linked_subject_id,
            ideal_num_sections=0,
            max_enrollment=max_enrollment,
            min_enrollment=min_enrollment,
            min_meetings=min_meetings,
            max_meetings=max_meetings,
            row_id=row_id
        )
        
        # Attach subject_type name for lab detection (used by is_lab_subject helper)
        if subject_type_id and subject_type_id in subject_types_map:
            sub._subject_type_name = subject_types_map[subject_type_id].name
        else:
            sub._subject_type_name = None
        
        subjects_map[subject_id] = sub

    batches = []
    for _, row in df_batches.iterrows():
        # Skip batches with zero or negative population
        population = int(row['population'])
        if population <= 0:
            continue
        
        # Parse enrolled subject IDs (semicolon-delimited integers)
        subject_ids = []
        if pd.notna(row.get('enrolled_subjects')) and str(row['enrolled_subjects']).strip():
            subject_ids = [int(sid.strip()) for sid in str(row['enrolled_subjects']).split(';') if sid.strip()]
        
        batch_subjects = [subjects_map[sid] for sid in subject_ids if sid in subjects_map]
        for sub in batch_subjects:
            sub.enrolling_batch_ids.append(row['batch_id'])
        
        # Get row_id from id column if present
        row_id = int(row['id']) if 'id' in df_batches.columns and pd.notna(row.get('id')) else None
        
        batches.append(Batch(
            batch_id=row['batch_id'],
            program_id=row['program_id'],
            population=population,
            subjects=batch_subjects,
            banned_times=banned_times_by_batch[row['batch_id']],
            external_meetings=external_meetings_by_batch[row['batch_id']],
            row_id=row_id
        ))

    for sub in sorted(subjects_map.values(), key=lambda s: s.subject_id):
        total_enrollment = sum(b.population for b in batches if sub.subject_id in [s.subject_id for s in b.subjects])
        if total_enrollment > 0:
            # Use max_enrollment if set, otherwise default to 40
            if sub.max_enrollment and sub.max_enrollment > 0:
                max_size = sub.max_enrollment
            else:
                max_size = 40  # Default fallback
            sub.ideal_num_sections = ((total_enrollment + max_size - 1) // max_size )
         
    subjects = sorted(subjects_map.values(), key=lambda s: s.subject_id)
    return subjects, rooms, faculty, batches, subjects_map

def filter_infeasible_subjects(subjects, rooms, faculty, batches, config):
    """
    Removes subjects that cannot be feasibly scheduled due to ANY of:
    0. No meetings scheduled (max_meetings == 0 or required_weekly_minutes == 0)
    1. No qualified faculty available
    2. No batches enrolled
    3. Incompatible room type (room_type_id doesn't exist in available rooms)
    
    Also cleans up all references to removed subjects from batches and faculty.
    Writes removed_subjects.txt file with simple format.
    
    Args:
        subjects: List of Subject objects
        rooms: List of Room objects
        faculty: List of Faculty objects
        batches: List of Batch objects
        config: Configuration dict
    
    Returns:
        Tuple of (filtered_subjects, removed_subjects_with_reasons)
    """
    # Build set of available room types
    available_room_types = set()
    for room in rooms:
        if hasattr(room, 'room_type_id') and room.room_type_id:
            available_room_types.add(room.room_type_id)
    
    filtered_subjects = []
    removed_subjects_with_reasons = []
    removed_subject_ids = set()
    
    print("\n" + "=" * 80)
    print("FILTERING INFEASIBLE SUBJECTS")
    print("=" * 80)
    print(f"Available room types: {sorted(available_room_types)}")
    print()
    
    for subject in subjects:
        # Check 0: Does the subject have any meetings scheduled?
        has_meetings = False
        if hasattr(subject, 'max_meetings') and subject.max_meetings and subject.max_meetings > 0:
            has_meetings = True
        if hasattr(subject, 'required_weekly_minutes') and subject.required_weekly_minutes and subject.required_weekly_minutes > 0:
            has_meetings = True
        
        # Check 1: Is there at least one qualified faculty?
        has_qualified_faculty = False
        for fac in faculty:
            if hasattr(fac, 'preferred_subject_ids') and subject.subject_id in fac.preferred_subject_ids:
                has_qualified_faculty = True
                break
            if hasattr(fac, 'qualified_subject_ids') and subject.subject_id in fac.qualified_subject_ids:
                has_qualified_faculty = True
                break
        
        # Check 2: Is there at least one batch enrolled?
        has_enrolled_batch = False
        for batch in batches:
            if hasattr(batch, 'subjects'):
                if any(sub.subject_id == subject.subject_id for sub in batch.subjects):
                    has_enrolled_batch = True
                    break
        
        # Check 3: Does a compatible room type exist?
        has_compatible_room = False
        if hasattr(subject, 'room_type_id') and subject.room_type_id:
            # Subject requires a specific room type
            if subject.room_type_id in available_room_types:
                has_compatible_room = True
        else:
            # Subject has no room type requirement - any room works
            has_compatible_room = True
        
        # Remove if ANY condition fails (OR logic)
        if not has_meetings or not has_qualified_faculty or not has_enrolled_batch or not has_compatible_room:
            # Build list of reasons for removal (simple format)
            reasons = []
            if not has_meetings:
                reasons.append("Meetings")
            if not has_qualified_faculty:
                reasons.append("Teacher")
            if not has_enrolled_batch:
                reasons.append("Students")
            if not has_compatible_room:
                reasons.append("Room Type")
            
            # Store subject and reasons
            removed_subjects_with_reasons.append({
                "subject": subject,
                "subject_id": subject.subject_id,
                "reasons": reasons
            })
            removed_subject_ids.add(subject.subject_id)
            
            # Print removal info
            reasons_str = ", ".join([f"No {r}" for r in reasons])
            print(f"REMOVED: {subject.subject_id} - {reasons_str}")
        else:
            filtered_subjects.append(subject)
    
    # Clean up references to removed subjects
    if removed_subject_ids:
        print(f"\nCleaning up references to {len(removed_subject_ids)} removed subjects...")
        
        # Remove from batch.subjects
        for batch in batches:
            if hasattr(batch, 'subjects'):
                original_count = len(batch.subjects)
                batch.subjects = [sub for sub in batch.subjects if sub.subject_id not in removed_subject_ids]
                removed_count = original_count - len(batch.subjects)
                if removed_count > 0:
                    print(f"   Batch {batch.batch_id}: Removed {removed_count} subject reference(s)")
        
        # Remove from faculty.preferred_subjects
        # Remove from faculty.preferred_subject_ids
        for fac in faculty:
            if hasattr(fac, 'preferred_subject_ids'):
                original_count = len(fac.preferred_subject_ids)
                fac.preferred_subject_ids = {sid for sid in fac.preferred_subject_ids if sid not in removed_subject_ids}
                removed_count = original_count - len(fac.preferred_subject_ids)
                if removed_count > 0:
                    print(f"   Faculty {fac.name}: Removed {removed_count} from preferred_subject_ids")
        
        # Remove from faculty.qualified_subject_ids
        for fac in faculty:
            if hasattr(fac, 'qualified_subject_ids'):
                original_count = len(fac.qualified_subject_ids)
                fac.qualified_subject_ids = {sid for sid in fac.qualified_subject_ids if sid not in removed_subject_ids}
                removed_count = original_count - len(fac.qualified_subject_ids)
                if removed_count > 0:
                    print(f"   Faculty {fac.name}: Removed {removed_count} from qualified_subject_ids")
    
    print()
    print(f"Summary:")
    print(f"   Total subjects: {len(subjects)}")
    print(f"   Removed: {len(removed_subjects_with_reasons)}")
    print(f"   Remaining: {len(filtered_subjects)}")
    print("=" * 80 + "\n")
    
    # Write removed subjects to .txt file
    if removed_subjects_with_reasons:
        output_file = "removed_subjects.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("REMOVED SUBJECTS\n")
            f.write("=" * 60 + "\n\n")
            for item in removed_subjects_with_reasons:
                sub = item["subject"]
                subject_name = sub.name if hasattr(sub, 'name') else item['subject_id']
                reasons_str = ", ".join([f"No {r}" for r in item["reasons"]])
                f.write(f"{item['subject_id']} ({subject_name}) - {reasons_str}\n")
        print(f"Removed subjects list saved to: {output_file}")
    
    return filtered_subjects, removed_subjects_with_reasons

def run_two_pass_scheduler(config, subjects, rooms, faculty, batches, subjects_map,
                          seed, pass1_time, pass2_time, output_folder, deterministic_mode=False):
    """
    Run two-pass optimization: Pass 1 (structural) â†’ Pass 2 (preferences).
    This is the EXACT same logic used in non-seed-search mode.
    
    Args:
        config: Configuration dictionary
        subjects, rooms, faculty, batches, subjects_map: Data structures
        seed: Random seed for this run
        pass1_time: Time limit for Pass 1 in seconds
        pass2_time: Time limit for Pass 2 in seconds
        output_folder: Directory to save outputs
        deterministic_mode: Whether to use single-threaded mode
    
    Returns:
        (status, solver, results) tuple
    """
    print("\n" + "="*70)
    print(f"PASS 1: STRUCTURAL OPTIMIZATION (seed: {seed})")
    print("="*70)
    
    # ============================================================================
    # PASS 1: Minimal model (NO soft constraints)
    # ============================================================================
    status_pass1, solver_pass1, results_pass1 = run_scheduler(
        config, subjects, rooms, faculty, batches, subjects_map,
        time_limit=pass1_time,
        random_seed=seed,
        deterministic_mode=deterministic_mode,
        output_folder=output_folder,
        pass_mode="pass1"
    )
    
    if status_pass1 not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        print("Pass 1 failed! Cannot proceed to Pass 2.")
        return status_pass1, solver_pass1, results_pass1
    
    structural_minimum = results_pass1.get("pass1_structural_violations", 0)
    flush_print(f"\nPass 1 complete! Structural minimum: {structural_minimum}")
    
    # Save Pass 1 outputs
    flush_print("Generating Pass 1 violation report...")
    try:
        pass1_violation_report_path = os.path.join(output_folder, "pass1_violation_report.txt")
        human_readable_violation_report(
            solver=solver_pass1,
            results=results_pass1,
            config=config,
            faculty=faculty,
            rooms=rooms,
            batches=batches,
            subjects_map=subjects_map,
            output_file=pass1_violation_report_path
        )
        flush_print(f"Pass 1 violation report saved")
    except Exception as e:
        flush_print(f"Error generating violation report: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
    
    flush_print("Generating Pass 1 raw violations Excel...")
    try:
        pass1_raw_violations_path = os.path.join(output_folder, "pass1_raw_violations.xlsx")
        print_raw_violations(
            solver_pass1, 
            results_pass1, 
            faculty, 
            batches,
            config,
            print_to_terminal=False,
            save_to_file=True,
            filename=pass1_raw_violations_path
        )
        flush_print(f"Pass 1 raw violations saved")
    except Exception as e:
        flush_print(f"Error generating raw violations: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
    
    # ============================================================================
    # EXPORT PASS 1 SOLUTION TO DATABASE
    # ============================================================================
    flush_print("Exporting Pass 1 schedule to database...")
    try:
        pass1_db_path = os.path.join(output_folder, "pass1_schedule.db")
        save_schedule_with_full_view(status_pass1, solver_pass1, results_pass1, config, subjects, rooms, faculty, batches, subjects_map, db_path=pass1_db_path)
        flush_print(f"Pass 1 schedule database saved to: {pass1_db_path}")
    except Exception as e:
        flush_print(f"Error exporting Pass 1 to database: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
    
    # ============================================================================
    # EXTRACT PASS 1 STRUCTURAL SLACK VARIABLE VALUES (for locking in Pass 2)
    # ============================================================================
    print("Extracting Pass 1 structural slack values for locking...")
    pass1_hints = {
        "is_dummy_faculty": {},
        "is_dummy_room": {},
        "duration_violations": {},
        "faculty_day_gaps": {},
        "batch_day_gaps": {}
    }
    
    for key, var in results_pass1["violations"].get("is_dummy_faculty", {}).items():
        pass1_hints["is_dummy_faculty"][key] = solver_pass1.Value(var)
    
    for key, var in results_pass1["violations"].get("is_dummy_room", {}).items():
        pass1_hints["is_dummy_room"][key] = solver_pass1.Value(var)
    
    for key, var in results_pass1["violations"].get("duration_violations", {}).items():
        pass1_hints["duration_violations"][key] = solver_pass1.Value(var)
    
    for f_idx, gap_vars in results_pass1["violations"].get("faculty_day_gaps", {}).items():
        pass1_hints["faculty_day_gaps"][f_idx] = [solver_pass1.Value(var) for var in gap_vars]
    
    for b_idx, gap_vars in results_pass1["violations"].get("batch_day_gaps", {}).items():
        pass1_hints["batch_day_gaps"][b_idx] = [solver_pass1.Value(var) for var in gap_vars]
    
    print(f"  Extracted {len(pass1_hints['is_dummy_faculty'])} dummy faculty hints")
    print(f"  Extracted {len(pass1_hints['is_dummy_room'])} dummy room hints")
    print(f"  Extracted {len(pass1_hints['duration_violations'])} duration violation hints")
    
    # ============================================================================
    # AGGRESSIVE MEMORY CLEANUP BETWEEN PASSES
    # ============================================================================
    print("\nCleaning up Pass 1 memory...")
    
    # Delete solver and results explicitly
    del solver_pass1
    del results_pass1
    
    # Force garbage collection multiple times to ensure all OR-Tools objects are released
    gc.collect()
    gc.collect()
    gc.collect()
    
    # Small delay to allow OS to reclaim memory
    time.sleep(0.5)
    
    print("Memory cleanup complete")
    
    # ============================================================================
    # PASS 2: Full model (WITH soft constraints)
    # ============================================================================
    print("\n" + "="*70)
    print(f"PASS 2: PREFERENCE OPTIMIZATION (seed: {seed})")
    print("="*70)
    
    status, solver, results = run_scheduler(
        config, subjects, rooms, faculty, batches, subjects_map,
        time_limit=pass2_time,
        random_seed=seed,
        deterministic_mode=deterministic_mode,
        output_folder=output_folder,
        pass_mode="pass2",
        structural_limit=structural_minimum,
        pass1_hints=pass1_hints
    )
    
    return status, solver, results

if __name__ == '__main__':
    print("Starting scheduler...")
    config = load_config()
    model = cp_model.CpModel()
    subjects, rooms, faculty, batches, subjects_map = load_data(config, model)
    
    # Filter infeasible subjects if enabled
    if config.get("FILTER_INFEASIBLE_SUBJECTS", False):
        subjects, removed_subjects = filter_infeasible_subjects(subjects, rooms, faculty, batches, config)
        # Update subjects_map to only include filtered subjects
        subjects_map = {sub.subject_id: sub for sub in subjects}
    else:
        print("\nInfeasible subject filtering is DISABLED")
        print("   Set FILTER_INFEASIBLE_SUBJECTS to true in config.json to enable\n")

    # ============ SEED CONFIGURATION ============
    # Set to True to use random seed search, False to use custom seed
    USE_RANDOM_SEED = False
    CUSTOM_SEED = 894646  # Used when USE_RANDOM_SEED = False
    is_deterministic_active = False
    # ============================================

    hour_time_limit = 0
    minute_time_limit = 15
    
    hour_time_seed = 0
    minute_time_seed = 15
    
    total_time_limit_input = round(((hour_time_limit * 60) + minute_time_limit) * 60)
    time_per_seed_input = round((hour_time_seed * 60) + minute_time_seed) * 60 
    num_seeds_input = ceil(total_time_limit_input // time_per_seed_input)

    # Count dataset entities for folder naming
    num_faculty = len(faculty)
    num_subjects = len(subjects)
    num_batches = len(batches)
    num_rooms = len(rooms)
    
    # Count room types and subject types from CSV files
    DATA_FOLDER = 'data'
    df_room_types = pd.read_csv(f'{DATA_FOLDER}/room_types.csv')
    df_subject_types = pd.read_csv(f'{DATA_FOLDER}/subject_types.csv')
    num_room_types = len(df_room_types)
    num_subject_types = len(df_subject_types)

    # Create output folder for this run
    output_folder = create_output_folder(
        CUSTOM_SEED, is_deterministic_active,
        num_faculty=num_faculty,
        num_subjects=num_subjects,
        num_batches=num_batches,
        num_rooms=num_rooms,
        num_room_types=num_room_types,
        num_subject_types=num_subject_types
    )
    print(f"Output folder: {output_folder}")

    if is_deterministic_active:
        print("Deterministic Mode Activated")
    else:
        print("Deterministic Mode De-activated")

    if USE_RANDOM_SEED:
        # ============================================================================
        # SEED SEARCH MODE: Try multiple seeds and keep the best
        # ============================================================================
        print("Running with RANDOM SEED SEARCH")
        print(f"Up to {num_seeds_input} seeds, {time_per_seed_input}s each, {total_time_limit_input}s total")
        print("=" * 70)
        
        best_solution = None
        best_penalty = float('inf')
        best_seed = None
        start_time = time.time()
        seeds_tried = 0
        
        # Time allocation per seed (30% Pass 1, 70% Pass 2)
        pass1_time_per_seed = int(time_per_seed_input * 0.3)
        pass2_time_per_seed = time_per_seed_input 
        """ - pass1_time_per_seed """
        
        for i in range(num_seeds_input):
            elapsed = time.time() - start_time
            if elapsed >= total_time_limit_input:
                print(f"\nTotal time limit reached ({total_time_limit_input}s)")
                break
            
            seed = random.randint(0, 999999)
            seeds_tried += 1
            print(f"\nAttempt {seeds_tried}/{num_seeds_input} - Seed: {seed}")
            
            # Create subfolder for this seed
            seed_folder = os.path.join(output_folder, f"seed_{seed}")
            os.makedirs(seed_folder, exist_ok=True)
            
            # Run two-pass optimization (EXACT same logic as non-seed search)
            status, solver, results = run_two_pass_scheduler(
                config, subjects, rooms, faculty, batches, subjects_map,
                seed=seed,
                pass1_time=pass1_time_per_seed,
                pass2_time=pass2_time_per_seed*1,
                output_folder=seed_folder,
                deterministic_mode=is_deterministic_active
            )
            
            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                penalty = solver.ObjectiveValue()
                print(f"   Solution found - Penalty: {penalty}")
                
                # Save full outputs for this seed
                violation_report_path = os.path.join(seed_folder, "violation_report.txt")
                human_readable_violation_report(
                    solver=solver,
                    results=results,
                    config=config,
                    faculty=faculty,
                    rooms=rooms,
                    batches=batches,
                    subjects_map=subjects_map,
                    output_file=violation_report_path
                )
                
                raw_violations_path = os.path.join(seed_folder, "raw_violations.xlsx")
                print_raw_violations(
                    solver, 
                    results, 
                    faculty, 
                    batches,
                    config,
                    print_to_terminal=False,
                    save_to_file=True,
                    filename=raw_violations_path
                )
                
                db_path = os.path.join(seed_folder, "schedule.db")
                save_schedule_with_full_view(status, solver, results, config, subjects, rooms, faculty, batches, db_path=db_path)
                
                print(f"   Outputs saved to: {seed_folder}")
                
                # Track best solution
                if penalty < best_penalty:
                    best_penalty = penalty
                    best_solution = (status, solver, results)
                    best_seed = seed
                    print(f"   NEW BEST SOLUTION! (Penalty: {penalty})")
            else:
                print(f"   No solution found")
        
        print("\n" + "=" * 70)
        if best_solution:
            status, solver, results = best_solution
            print(f"Seed search complete!")
            print(f"   Best seed: {best_seed}")
            print(f"   Best penalty: {best_penalty}")
            print(f"   Seeds tried: {seeds_tried}")
            print(f"   Best solution: {os.path.join(output_folder, f'seed_{best_seed}')}")
        else:
            print("No feasible solution found during seed search.")
            status, solver, results = None, None, None
    else:
        # ============================================================================
        # SINGLE SEED MODE: Run with custom seed
        # ============================================================================
        print(f"Running with CUSTOM SEED: {CUSTOM_SEED}")
        
        # Time allocation (30% Pass 1, 70% Pass 2 - same as seed search)
        pass1_time = int(total_time_limit_input * 1)
        pass2_time = total_time_limit_input 
        """ - pass1_time """
        
        # Run two-pass optimization (EXACT same function as seed search uses)
        status, solver, results = run_two_pass_scheduler(
            config, subjects, rooms, faculty, batches, subjects_map,
            seed=CUSTOM_SEED,
            pass1_time=pass1_time,
            pass2_time=pass2_time*1,
            output_folder=output_folder,
            deterministic_mode=is_deterministic_active
        )

    # ============================================================================
    # SAVE FINAL OUTPUTS (for both seed search and single seed modes)
    # ============================================================================
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Save violation report to output folder
        violation_report_path = os.path.join(output_folder, "violation_report.txt")
        human_readable_violation_report(
            solver=solver,
            results=results,
            config=config,
            faculty=faculty,
            rooms=rooms,
            batches=batches,
            subjects_map=subjects_map,
            output_file=violation_report_path
        )
        print(f"\nViolation report saved to: {violation_report_path}")

        # Save raw violations to output folder (no terminal output)
        raw_violations_path = os.path.join(output_folder, "raw_violations.xlsx")
        print_raw_violations(
            solver, 
            results, 
            faculty, 
            batches,
            config,
            print_to_terminal=False,
            save_to_file=True,
            filename=raw_violations_path
        )

        # Save database to output folder
        db_path = os.path.join(output_folder, "schedule.db")
        save_schedule_with_full_view(status, solver, results, config, subjects, rooms, faculty, batches, subjects_map, db_path=db_path)
        
        # Export detailed soft time violation reports
        export_soft_time_violations_detailed(solver, results, config, faculty, batches, output_folder)
        
        print(f"\nAll outputs saved to: {output_folder}")

    else:
        print("\nNo feasible solution found. No outputs generated.")
