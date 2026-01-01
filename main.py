# main.py
import collections
import sqlite3
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
from scheduler import run_scheduler, print_raw_violations
import pandas as pd

# Enable immediate output flushing for debugging hangs
def flush_print(*args, **kwargs):
    print(*args, **kwargs)
    sys.stdout.flush()

def create_output_folder(seed, is_deterministic, num_faculty=0, num_subjects=0, num_batches=0, num_rooms=0, num_room_types=0, num_subject_types=0):
    """
    Creates a unique output folder for this scheduler run.
    
    Folder naming: outputs/{seed}_{YYYYMMDD}_{HHMMSS}_{mode}_F{faculty}_S{subjects}_SB{batches}_R{rooms}_RT{room_types}_ST{subject_types}/
    
    Returns:
        str: Absolute path to the created output folder
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "deterministic" if is_deterministic else "nondeterministic"
    
    # Build dataset size suffix
    dataset_info = f"F{num_faculty}_S{num_subjects}_SB{num_batches}_R{num_rooms}_RT{num_room_types}_ST{num_subject_types}"
    
    folder_name = f"{seed}_{timestamp}_{mode}_{dataset_info}"
    
    # Create outputs directory if it doesn't exist
    base_dir = os.path.dirname(os.path.abspath(__file__))
    outputs_dir = os.path.join(base_dir, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    
    # Create the run-specific folder
    run_folder = os.path.join(outputs_dir, folder_name)
    os.makedirs(run_folder, exist_ok=True)
    
    return run_folder

def load_config(path='config.json'):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"FATAL: Could not load or parse {path}. Error: {e}")
        exit(1)

def load_data(config, model):
    # Data folder path (change this to switch between data sets)
    DATA_FOLDER = 'data'
    
    # Load lookup tables first
    try:
        df_room_types = pd.read_csv(f'{DATA_FOLDER}/room_types.csv')
        print(f"✓ Successfully loaded {DATA_FOLDER}/room_types.csv")
    except FileNotFoundError:
        print(f"⚠️ WARNING: {DATA_FOLDER}/room_types.csv not found. Creating empty lookup.")
        df_room_types = pd.DataFrame(columns=['id', 'name', 'description'])
    
    try:
        df_subject_types = pd.read_csv(f'{DATA_FOLDER}/subject_types.csv')
        print(f"✓ Successfully loaded {DATA_FOLDER}/subject_types.csv")
    except FileNotFoundError:
        print(f"⚠️ WARNING: {DATA_FOLDER}/subject_types.csv not found. Creating empty lookup.")
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
    
    print(f"✓ Loaded {len(room_types_map)} room types")
    print(f"✓ Loaded {len(subject_types_map)} subject types")
    
    # Load main entity tables
    df_faculty = pd.read_csv(f'{DATA_FOLDER}/faculty.csv')
    df_rooms = pd.read_csv(f'{DATA_FOLDER}/rooms.csv')
    df_subjects = pd.read_csv(f'{DATA_FOLDER}/subjects.csv')
    df_batches = pd.read_csv(f'{DATA_FOLDER}/student_batches.csv')

    # --- Fail-safe for banned_times.csv ---
    try:
        df_banned_times = pd.read_csv(f'{DATA_FOLDER}/banned_times.csv', dtype={'start_time': str, 'end_time': str})
        print(f"✓ Successfully loaded {DATA_FOLDER}/banned_times.csv")
    except FileNotFoundError:
        print(f"⚠️ WARNING: {DATA_FOLDER}/banned_times.csv not found. Continuing without banned times.")
        # Create an empty DataFrame with the expected columns
        df_banned_times = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time'])
    except pd.errors.EmptyDataError:
        print(f"⚠️ WARNING: {DATA_FOLDER}/banned_times.csv is empty. Continuing without banned times.")
        df_banned_times = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time'])
    except Exception as e:
        print(f"❌ ERROR reading {DATA_FOLDER}/banned_times.csv: {e}. Continuing without banned times.")
        df_banned_times = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time'])

    # --- Fail-safe for external_meetings.csv ---
    try:
        df_external_meetings = pd.read_csv(f'{DATA_FOLDER}/external_meetings.csv', dtype={'start_time': str, 'end_time': str})
        print(f"✓ Successfully loaded {DATA_FOLDER}/external_meetings.csv")
    except FileNotFoundError:
        print(f"⚠️ WARNING: {DATA_FOLDER}/external_meetings.csv not found. Continuing without external meetings.")
        # Create an empty DataFrame with the expected columns
        df_external_meetings = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time', 'event_name', 'description'])
    except pd.errors.EmptyDataError:
        print(f"⚠️ WARNING: {DATA_FOLDER}/external_meetings.csv is empty. Continuing without external meetings.")
        df_external_meetings = pd.DataFrame(columns=['batch_id', 'day', 'start_time', 'end_time', 'event_name', 'description'])
    except Exception as e:
        print(f"❌ ERROR reading {DATA_FOLDER}/external_meetings.csv: {e}. Continuing without external meetings.")
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
    
    Args:
        subjects: List of Subject objects
        rooms: List of Room objects
        faculty: List of Faculty objects
        batches: List of Batch objects
        config: Configuration dict
    
    Returns:
        Tuple of (filtered_subjects, removed_subjects)
    """
    # Build set of available room types
    available_room_types = set()
    for room in rooms:
        if hasattr(room, 'room_type_id') and room.room_type_id:
            available_room_types.add(room.room_type_id)
    
    filtered_subjects = []
    removed_subjects = []
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
            removed_subjects.append(subject)
            removed_subject_ids.add(subject.subject_id)
            room_type_str = str(subject.room_type_id) if hasattr(subject, 'room_type_id') and subject.room_type_id else "None"
            print(f"❌ REMOVED: {subject.subject_id} (Room Type: {room_type_str})")
            print(f"   - No meetings scheduled: {not has_meetings}")
            print(f"   - No qualified faculty: {not has_qualified_faculty}")
            print(f"   - No enrolled batches: {not has_enrolled_batch}")
            print(f"   - No compatible rooms: {not has_compatible_room}")
        else:
            filtered_subjects.append(subject)
    
    # Clean up references to removed subjects
    if removed_subject_ids:
        print(f"\n🧹 Cleaning up references to {len(removed_subject_ids)} removed subjects...")
        
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
    print(f"📊 Summary:")
    print(f"   Total subjects: {len(subjects)}")
    print(f"   Removed: {len(removed_subjects)}")
    print(f"   Remaining: {len(filtered_subjects)}")
    print("=" * 80 + "\n")
    
    return filtered_subjects, removed_subjects

def save_schedule_to_db(status, solver, results, config, subjects, rooms, faculty, batches, db_path=None):
    if status != cp_model.OPTIMAL and status != cp_model.FEASIBLE:
        print("\nNo optimal or feasible solution found. Nothing to save to database.")
        return

    # Use provided path or default
    if db_path is None:
        os.makedirs("outputs", exist_ok=True)
        db_path = os.path.join("outputs", "schedule.db")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Drop existing tables to ensure a fresh start
    cursor.execute('DROP TABLE IF EXISTS schedule_meetings')
    cursor.execute('DROP TABLE IF EXISTS schedule_meetings_id')
    cursor.execute('DROP TABLE IF EXISTS section_assignments')
    cursor.execute('DROP TABLE IF EXISTS section_assignments_id')
    cursor.execute('DROP TABLE IF EXISTS faculty')
    cursor.execute('DROP TABLE IF EXISTS rooms')
    cursor.execute('DROP TABLE IF EXISTS batches')

    # Create reference tables
    cursor.execute('CREATE TABLE faculty (faculty_id TEXT PRIMARY KEY, name TEXT, max_hours INTEGER)')
    cursor.execute('CREATE TABLE rooms (room_id TEXT PRIMARY KEY, capacity INTEGER, type TEXT)')
    cursor.execute('CREATE TABLE batches (batch_id TEXT PRIMARY KEY, program_id TEXT, population INTEGER)')
    
    # Create section_assignments table (WHO teaches WHAT to WHOM)
    cursor.execute('''
        CREATE TABLE section_assignments (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id TEXT NOT NULL,
            section_index INTEGER NOT NULL,
            faculty_id TEXT,
            batches_enrolled TEXT,
            UNIQUE(subject_id, section_index)
        )
    ''')
    
    # Create section_assignments_id table (row ID version)
    cursor.execute('''
        CREATE TABLE section_assignments_id (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER,
            section_index INTEGER NOT NULL,
            faculty_id INTEGER,
            batch_ids TEXT,
            UNIQUE(subject_id, section_index)
        )
    ''')
    
    # Create schedule_meetings table (WHEN and WHERE classes happen)
    cursor.execute('''
        CREATE TABLE schedule_meetings (
            meeting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            day_of_week TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            room_id TEXT,
            FOREIGN KEY (assignment_id) REFERENCES section_assignments(assignment_id)
        )
    ''')
    
    # Create schedule_meetings_id table (row ID version)
    cursor.execute('''
        CREATE TABLE schedule_meetings_id (
            meeting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            day_of_week TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            room_id INTEGER,
            FOREIGN KEY (assignment_id) REFERENCES section_assignments_id(assignment_id)
        )
    ''')

    # Populate faculty, rooms, batches
    for f in faculty:
        cursor.execute("INSERT INTO faculty (faculty_id, name, max_hours) VALUES (?, ?, ?)", (f.id, f.name, f.max_hours))
    for r in rooms:
        cursor.execute("INSERT INTO rooms (room_id, capacity, type) VALUES (?, ?, ?)", (r.room_id, r.capacity, r.room_type_id))
    for b in batches:
        cursor.execute("INSERT INTO batches (batch_id, program_id, population) VALUES (?, ?, ?)", (b.batch_id, b.program_id, b.population))

    print(f"\n--- Saving schedule to {db_path} ---")

    # Debug counters
    total_sections_saved = 0
    total_meetings_saved = 0
    
    # Track assignment_id mapping for linking meetings
    assignment_id_map = {}  # key: (sub_id, sec_idx) -> assignment_id

    # STEP 1: Insert section assignments (WHO teaches WHAT to WHOM)
    processed_sections = set()
    DUMMY_FACULTY_IDX = results.get("DUMMY_FACULTY_IDX", len(faculty))
    DUMMY_ROOM_IDX = results.get("DUMMY_ROOM_IDX", len(rooms))
    
    for (sub_id, sec_idx), room_var in results["assigned_room"].items():
        section_key = (sub_id, sec_idx)
        if section_key in processed_sections:
            continue
        processed_sections.add(section_key)
        
        faculty_idx = solver.Value(results["assigned_faculty"][(sub_id, sec_idx)])
        room_idx = solver.Value(room_var)

        # Handle dummy faculty (use placeholder)
        if faculty_idx == DUMMY_FACULTY_IDX:
            faculty_id = "UNASSIGNED"
            faculty_row_id = None
        elif 0 <= faculty_idx < len(faculty):
            faculty_id = faculty[faculty_idx].id
            faculty_row_id = faculty[faculty_idx].row_id
        else:
            continue  # Invalid index, skip
        
        # Handle dummy room (use placeholder)
        if room_idx == DUMMY_ROOM_IDX:
            room_id = "UNASSIGNED"
            room_row_id = None
        elif 0 <= room_idx < len(rooms):
            room_id = rooms[room_idx].room_id
            room_row_id = rooms[room_idx].row_id
        else:
            continue  # Invalid index, skip
        
        # Get enrolled batches
        assigned_batches_to_section = []
        assigned_batch_ids = []  # For row ID version
        for b_idx, batch in enumerate(batches):
            assignment_key = (sub_id, sec_idx, b_idx)
            if assignment_key in results["section_assignments"]:
                is_assigned = solver.Value(results["section_assignments"][assignment_key])
                if is_assigned:
                    assigned_batches_to_section.append(batch.batch_id)
                    if batch.row_id is not None:
                        assigned_batch_ids.append(batch.row_id)
        
        if assigned_batches_to_section:  # Only save if batches are enrolled
            # Insert into section_assignments (string version)
            batches_str = ';'.join(assigned_batches_to_section)
            cursor.execute('''
                INSERT INTO section_assignments (subject_id, section_index, faculty_id, batches_enrolled)
                VALUES (?, ?, ?, ?)
            ''', (sub_id, sec_idx + 1, faculty_id, batches_str))

            assignment_id = cursor.lastrowid
            assignment_id_map[section_key] = (assignment_id, room_id, room_row_id)
            total_sections_saved += 1

            # Insert into section_assignments_id (row ID version)
            subject_row_id = subjects_map[sub_id].row_id if sub_id in subjects_map else None
            # faculty_row_id already set above based on dummy check
            batch_ids_str = ';'.join(map(str, assigned_batch_ids)) if assigned_batch_ids else None

            cursor.execute('''
                INSERT INTO section_assignments_id (subject_id, section_index, faculty_id, batch_ids)
                VALUES (?, ?, ?, ?)
            ''', (subject_row_id, sec_idx + 1, faculty_row_id, batch_ids_str))

    # STEP 2: Insert schedule meetings (WHEN and WHERE)
    for (sub_id, sec_idx), (assignment_id, room_id, room_row_id) in assignment_id_map.items():
        for d_idx, day in enumerate(config["SCHEDULING_DAYS"]):
            meeting_key = (sub_id, sec_idx, d_idx)
            meeting = results["meetings"][meeting_key]

            if solver.Value(meeting["is_active"]):
                start_abs_min = solver.Value(meeting["start"])
                duration = solver.Value(meeting["duration"])
                end_abs_min = start_abs_min + duration

                day_offset = d_idx * 1440
                start_min_of_day = start_abs_min - day_offset
                end_min_of_day = end_abs_min - day_offset
                start_hour, start_minute = divmod(start_min_of_day, 60)
                end_hour, end_minute = divmod(end_min_of_day, 60)

                start_time_str = f"{int(start_hour):02}:{int(start_minute):02}"
                end_time_str = f"{int(end_hour):02}:{int(end_minute):02}"

                # Insert into schedule_meetings (string version)
                cursor.execute('''
                    INSERT INTO schedule_meetings (assignment_id, day_of_week, start_time, end_time, duration_minutes, room_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (assignment_id, day, start_time_str, end_time_str, duration, room_id))

                # Insert into schedule_meetings_id (row ID version - same assignment_id)
                cursor.execute('''
                    INSERT INTO schedule_meetings_id (assignment_id, day_of_week, start_time, end_time, duration_minutes, room_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (assignment_id, day, start_time_str, end_time_str, duration, room_row_id))

                total_meetings_saved += 1

    # Print debug stats
    print(f"📊 Section assignments saved: {total_sections_saved}")
    print(f"📊 Meetings saved: {total_meetings_saved}")

    conn.commit()
    conn.close()
    print(f"✅ Schedule saved to: {db_path}")

def save_schedule_with_full_view(status, solver, results, config, subjects, rooms, faculty, batches, db_path=None):
    if status != cp_model.OPTIMAL and status != cp_model.FEASIBLE:
        print("\nNo optimal or feasible solution found. Nothing to save to database.")
        return

    # Use provided path or default
    if db_path is None:
        os.makedirs("outputs", exist_ok=True)
        db_path = os.path.join("outputs", "schedule.db")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Drop existing tables to ensure a fresh start
    cursor.execute('DROP TABLE IF EXISTS section_assignments')
    cursor.execute('DROP TABLE IF EXISTS section_assignments_id')
    cursor.execute('DROP TABLE IF EXISTS schedule_meetings')
    cursor.execute('DROP TABLE IF EXISTS schedule_meetings_id')
    cursor.execute('DROP TABLE IF EXISTS faculty')
    cursor.execute('DROP TABLE IF EXISTS rooms')
    cursor.execute('DROP TABLE IF EXISTS batches')
    cursor.execute('DROP TABLE IF EXISTS schedule_full_view')
    cursor.execute('DROP TABLE IF EXISTS schedule_full_view_id')

    # Create reference tables
    cursor.execute('CREATE TABLE faculty (faculty_id TEXT PRIMARY KEY, name TEXT, max_hours INTEGER)')
    cursor.execute('CREATE TABLE rooms (room_id TEXT PRIMARY KEY, capacity INTEGER, type TEXT)')
    cursor.execute('CREATE TABLE batches (batch_id TEXT PRIMARY KEY, program_id TEXT, population INTEGER)')
    
    # Create section_assignments table (WHO teaches WHAT to WHOM) - String IDs
    cursor.execute('''
        CREATE TABLE section_assignments (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id TEXT,
            section_index INTEGER,
            faculty_id TEXT,
            batches_enrolled TEXT,
            UNIQUE(subject_id, section_index)
        )
    ''')
    
    # Create section_assignments_id table (same as above but with integer row IDs only)
    cursor.execute('''
        CREATE TABLE section_assignments_id (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER,
            section_index INTEGER,
            faculty_id INTEGER,
            batch_ids TEXT,
            UNIQUE(subject_id, section_index)
        )
    ''')
    
    # Create schedule_meetings table (WHEN and WHERE) - references section_assignments
    cursor.execute('''
        CREATE TABLE schedule_meetings (
            meeting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT,
            duration_minutes INTEGER,
            room_id TEXT,
            event_name TEXT,
            batches_enrolled TEXT,
            FOREIGN KEY (assignment_id) REFERENCES section_assignments(assignment_id)
        )
    ''')
    
    # Create schedule_meetings_id table (same structure, references section_assignments_id)
    cursor.execute('''
        CREATE TABLE schedule_meetings_id (
            meeting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT,
            duration_minutes INTEGER,
            room_id INTEGER,
            event_name TEXT,
            batch_ids TEXT,
            FOREIGN KEY (assignment_id) REFERENCES section_assignments_id(assignment_id)
        )
    ''')
    
    # Create denormalized full view table (with string IDs)
    cursor.execute('''
        CREATE TABLE schedule_full_view (
            view_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id TEXT,
            section_index INTEGER,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT,
            duration_minutes INTEGER,
            room_id TEXT,
            faculty_name TEXT,
            batches_enrolled TEXT,
            event_name TEXT,
            description TEXT
        )
    ''')
    
    # Create denormalized full view table (with row IDs only)
    cursor.execute('''
        CREATE TABLE schedule_full_view_id (
            view_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER,
            section_index INTEGER,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT,
            duration_minutes INTEGER,
            room_id INTEGER,
            faculty_id INTEGER,
            batch_ids TEXT,
            event_name TEXT,
            description TEXT
        )
    ''')

    # Populate faculty, rooms, batches
    for f in faculty:
        cursor.execute("INSERT INTO faculty (faculty_id, name, max_hours) VALUES (?, ?, ?)", 
                      (f.id, f.name, f.max_hours))
    for r in rooms:
        cursor.execute("INSERT INTO rooms (room_id, capacity, type) VALUES (?, ?, ?)", 
                      (r.room_id, r.capacity, r.room_type_id))
    for b in batches:
        cursor.execute("INSERT INTO batches (batch_id, program_id, population) VALUES (?, ?, ?)", 
                      (b.batch_id, b.program_id, b.population))

    print(f"\n--- Saving schedule to {db_path} ---")

    total_sections_saved = 0
    total_meetings_saved = 0
    assignment_id_map = {}  # Maps (sub_id, sec_idx) -> assignment_id
    DUMMY_FACULTY_IDX = results.get("DUMMY_FACULTY_IDX", len(faculty))
    DUMMY_ROOM_IDX = results.get("DUMMY_ROOM_IDX", len(rooms))

    # STEP 1: Insert section assignments (WHO teaches WHAT to WHOM)
    for (sub_id, sec_idx), room_var in results["assigned_room"].items():
        faculty_idx = solver.Value(results["assigned_faculty"][(sub_id, sec_idx)])

        # Handle dummy faculty (use placeholder)
        if faculty_idx == DUMMY_FACULTY_IDX:
            faculty_id = "UNASSIGNED"
            faculty_row_id = None
        elif 0 <= faculty_idx < len(faculty):
            faculty_id = faculty[faculty_idx].id
            faculty_row_id = faculty[faculty_idx].row_id
        else:
            continue  # Invalid index, skip
        
        # Get room for this section (same for all days)
        room_idx = solver.Value(room_var)
        if room_idx == DUMMY_ROOM_IDX:
            room_id = "UNASSIGNED"
            room_row_id = None
        elif 0 <= room_idx < len(rooms):
            room_id = rooms[room_idx].room_id
            room_row_id = rooms[room_idx].row_id
        else:
            continue  # Invalid index, skip
        
        # Get assigned batches for this section
        assigned_batches_to_section = []
        for b_idx, batch in enumerate(batches):
            assignment_key = (sub_id, sec_idx, b_idx)
            if assignment_key in results["section_assignments"]:
                is_assigned = solver.Value(results["section_assignments"][assignment_key])
                if is_assigned:
                    assigned_batches_to_section.append({
                        'batch_id': batch.batch_id,
                        'batch_row_id': batch.row_id,
                        'population': batch.population
                    })
        
        # Only export sections with enrolled batches
        if not assigned_batches_to_section:
            continue
        
        # Create batches_enrolled string (semicolon-separated)
        batches_enrolled_str = ';'.join([
            f"{a['batch_id']} ({a['population']})" 
            for a in assigned_batches_to_section
        ])
        
        # Insert into section_assignments (string IDs)
        cursor.execute('''
            INSERT INTO section_assignments (subject_id, section_index, faculty_id, batches_enrolled)
            VALUES (?, ?, ?, ?)
        ''', (sub_id, sec_idx + 1, faculty_id, batches_enrolled_str))

        assignment_id_string = cursor.lastrowid
        assignment_id_map[(sub_id, sec_idx)] = (assignment_id_string, room_id, room_row_id)

        # Insert into section_assignments_id (integer row IDs)
        subject_row_id = subjects_map[sub_id].row_id if sub_id in subjects_map else None
        # faculty_row_id already set above based on dummy check

        batch_ids_list = [a['batch_row_id'] for a in assigned_batches_to_section if a['batch_row_id'] is not None]
        batch_ids_str = ';'.join(map(str, batch_ids_list)) if batch_ids_list else None

        cursor.execute('''
            INSERT INTO section_assignments_id (subject_id, section_index, faculty_id, batch_ids)
            VALUES (?, ?, ?, ?)
        ''', (subject_row_id, sec_idx + 1, faculty_row_id, batch_ids_str))
        
        total_sections_saved += 1

    # STEP 2: Insert schedule meetings (WHEN and WHERE)
    for (sub_id, sec_idx), (assignment_id, room_id, room_row_id) in assignment_id_map.items():
        for d_idx, day in enumerate(config["SCHEDULING_DAYS"]):
            meeting_key = (sub_id, sec_idx, d_idx)
            meeting = results["meetings"][meeting_key]

            if solver.Value(meeting["is_active"]):
                start_abs_min = solver.Value(meeting["start"])
                duration = solver.Value(meeting["duration"])
                end_abs_min = start_abs_min + duration

                day_offset = d_idx * 1440
                start_min_of_day = start_abs_min - day_offset
                end_min_of_day = end_abs_min - day_offset
                start_hour, start_minute = divmod(start_min_of_day, 60)
                end_hour, end_minute = divmod(end_min_of_day, 60)

                start_time_str = f"{int(start_hour):02}:{int(start_minute):02}"
                end_time_str = f"{int(end_hour):02}:{int(end_minute):02}"

                # Insert into schedule_meetings (references section_assignments)
                cursor.execute('''
                    INSERT INTO schedule_meetings (assignment_id, day_of_week, start_time, end_time, duration_minutes, room_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (assignment_id, day, start_time_str, end_time_str, duration, room_id))

                # Insert into schedule_meetings_id (same data, references section_assignments_id)
                cursor.execute('''
                    INSERT INTO schedule_meetings_id (assignment_id, day_of_week, start_time, end_time, duration_minutes, room_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (assignment_id, day, start_time_str, end_time_str, duration, room_row_id))

                total_meetings_saved += 1
    
    # Insert external meetings into schedule_meetings (string IDs)
    external_meetings_count = 0
    for batch in batches:
        for ext_meeting in batch.external_meetings:
            day = config["SCHEDULING_DAYS"][ext_meeting.day_index]
            
            # Convert minutes to HH:MM format
            start_hour, start_minute = divmod(ext_meeting.start_minutes, 60)
            end_hour, end_minute = divmod(ext_meeting.end_minutes, 60)
            start_time_str = f"{int(start_hour):02}:{int(start_minute):02}"
            end_time_str = f"{int(end_hour):02}:{int(end_minute):02}"
            
            duration_minutes = ext_meeting.end_minutes - ext_meeting.start_minutes
            
            cursor.execute('''
                INSERT INTO schedule_meetings (assignment_id, day_of_week, start_time, end_time, duration_minutes, room_id, event_name, batches_enrolled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (None, day, start_time_str, end_time_str, duration_minutes, None, ext_meeting.event_name, batch.batch_id))
            
            external_meetings_count += 1
    
    # Insert external meetings into schedule_meetings_id (row IDs)
    for batch in batches:
        for ext_meeting in batch.external_meetings:
            day = config["SCHEDULING_DAYS"][ext_meeting.day_index]
            
            start_hour, start_minute = divmod(ext_meeting.start_minutes, 60)
            end_hour, end_minute = divmod(ext_meeting.end_minutes, 60)
            start_time_str = f"{int(start_hour):02}:{int(start_minute):02}"
            end_time_str = f"{int(end_hour):02}:{int(end_minute):02}"
            
            duration_minutes = ext_meeting.end_minutes - ext_meeting.start_minutes
            
            cursor.execute('''
                INSERT INTO schedule_meetings_id (assignment_id, day_of_week, start_time, end_time, duration_minutes, room_id, event_name, batch_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (None, day, start_time_str, end_time_str, duration_minutes, None, ext_meeting.event_name, str(batch.row_id) if batch.row_id else None))

    print(f"📊 Section assignments saved: {total_sections_saved}")
    print(f"📊 Meetings saved: {total_meetings_saved}")
    print(f"📅 External meetings saved: {external_meetings_count}")

    # Populate the full view table with denormalized data (string IDs)
    cursor.execute('''
        INSERT INTO schedule_full_view
            (subject_id, section_index, day_of_week, start_time, end_time,
             duration_minutes, room_id, faculty_name, batches_enrolled, event_name, description)
        SELECT
            a.subject_id,
            a.section_index,
            m.day_of_week,
            m.start_time,
            m.end_time,
            m.duration_minutes,
            m.room_id,
            f.name AS faculty_name,
            a.batches_enrolled,
            NULL AS event_name,
            NULL AS description
        FROM schedule_meetings m
        JOIN section_assignments a ON m.assignment_id = a.assignment_id
        LEFT JOIN faculty f ON a.faculty_id = f.faculty_id
    ''')
    
    print(f"📋 Full view records created: {cursor.rowcount}")
    
    # Populate the full view table with row IDs only
    cursor.execute('''
        INSERT INTO schedule_full_view_id
            (subject_id, section_index, day_of_week, start_time, end_time,
             duration_minutes, room_id, faculty_id, batch_ids, event_name, description)
        SELECT
            a.subject_id,
            a.section_index,
            m.day_of_week,
            m.start_time,
            m.end_time,
            m.duration_minutes,
            m.room_id,
            a.faculty_id,
            a.batch_ids,
            NULL AS event_name,
            NULL AS description
        FROM schedule_meetings_id m
        JOIN section_assignments_id a ON m.assignment_id = a.assignment_id
    ''')
    
    print(f"📋 Full view ID records created: {cursor.rowcount}")
    
    # Insert external meetings into full view (string IDs)
    external_meetings_count = 0
    for batch in batches:
        for ext_meeting in batch.external_meetings:
            day = config["SCHEDULING_DAYS"][ext_meeting.day_index]
            
            # Convert minutes to HH:MM format
            start_hour, start_minute = divmod(ext_meeting.start_minutes, 60)
            end_hour, end_minute = divmod(ext_meeting.end_minutes, 60)
            start_time_str = f"{int(start_hour):02}:{int(start_minute):02}"
            end_time_str = f"{int(end_hour):02}:{int(end_minute):02}"
            
            duration_minutes = ext_meeting.end_minutes - ext_meeting.start_minutes
            
            # Use description if available, otherwise None
            description = getattr(ext_meeting, 'description', None)
            
            cursor.execute('''
                INSERT INTO schedule_full_view
                    (subject_id, section_index, day_of_week, start_time, end_time,
                     duration_minutes, room_id, faculty_name, batches_enrolled, event_name, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (None, None, day, start_time_str, end_time_str, 
                  duration_minutes, None, None, batch.batch_id, ext_meeting.event_name, description))
            
            external_meetings_count += 1
    
    print(f"📅 External meetings inserted: {external_meetings_count}")
    
    # Insert external meetings into full view (row IDs only)
    for batch in batches:
        for ext_meeting in batch.external_meetings:
            day = config["SCHEDULING_DAYS"][ext_meeting.day_index]
            
            start_hour, start_minute = divmod(ext_meeting.start_minutes, 60)
            end_hour, end_minute = divmod(ext_meeting.end_minutes, 60)
            start_time_str = f"{int(start_hour):02}:{int(start_minute):02}"
            end_time_str = f"{int(end_hour):02}:{int(end_minute):02}"
            
            duration_minutes = ext_meeting.end_minutes - ext_meeting.start_minutes
            description = getattr(ext_meeting, 'description', None)
            
            cursor.execute('''
                INSERT INTO schedule_full_view_id
                    (subject_id, section_index, day_of_week, start_time, end_time,
                     duration_minutes, room_id, faculty_id, batch_ids, event_name, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (None, None, day, start_time_str, end_time_str, 
                  duration_minutes, None, None, str(batch.row_id) if batch.row_id else None, 
                  ext_meeting.event_name, description))

    conn.commit()
    conn.close()
    print("✅ Schedule and full view saved successfully.")

def generate_violation_report(solver, results, config, faculty, rooms, batches, subjects_map, output_file="violation_report.txt"):
    """
    Generates a human-readable violation report and writes it to a text file.
    
    Args:
        solver: The CP-SAT solver with solution
        results: Dictionary containing violations from run_scheduler()
        config: Configuration dictionary
        faculty: List of Faculty objects
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
            f.write("✓ No structural violations - all hard constraints satisfied!\n\n")
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
                status = "⚠️ OVER MAX"
            elif total_mins < min_mins and min_mins > 0:
                status = "⚠️ UNDER MIN"
            else:
                status = "✓ OK"
            
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
                    violation_slots = get_violation_slots(violation_list, solver)
                    
                    if violation_slots:
                        ranges = find_consecutive_ranges(violation_slots)
                        for start_slot, end_slot in ranges:
                            # Apply forward offset
                            actual_start = start_slot + MAX_GAP_SLOTS
                            actual_end = end_slot + MAX_GAP_SLOTS + 1
                            
                            start_time = slot_to_time(actual_start, config["DAY_START_MINUTES"])
                            end_time = slot_to_time(actual_end, config["DAY_START_MINUTES"])
                            
                            violation_count = end_slot - start_slot + 1
                            excess_mins = violation_count * SLOT_SIZE
                            actual_gap = (MAX_GAP_SLOTS + violation_count) * SLOT_SIZE
                            max_gap = MAX_GAP_SLOTS * SLOT_SIZE
                            
                            penalty = violation_count * config["ConstraintPenalties"]["EXCESS_GAP_PER_SLOT"]
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
                    violation_slots = get_violation_slots(violation_list, solver)
                    
                    if violation_slots:
                        ranges = find_consecutive_ranges(violation_slots)
                        for start_slot, end_slot in ranges:
                            # Apply forward offset
                            actual_start = start_slot + MAX_GAP_SLOTS
                            actual_end = end_slot + MAX_GAP_SLOTS + 1
                            
                            start_time = slot_to_time(actual_start, config["DAY_START_MINUTES"])
                            end_time = slot_to_time(actual_end, config["DAY_START_MINUTES"])
                            
                            violation_count = end_slot - start_slot + 1
                            excess_mins = violation_count * SLOT_SIZE
                            actual_gap = (MAX_GAP_SLOTS + violation_count) * SLOT_SIZE
                            max_gap = MAX_GAP_SLOTS * SLOT_SIZE
                            
                            penalty = violation_count * config["ConstraintPenalties"]["EXCESS_GAP_PER_SLOT"]
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
        MIN_BLOCK_SLOTS = int(config.get("MIN_CONTINUOUS_CLASS_HOURS") * 60 / SLOT_SIZE)
        
        # Faculty under minimum blocks
        if "faculty_under_minimum_block" in results["violations"]:
            for f_idx in results["violations"]["faculty_under_minimum_block"]:
                for day_idx in results["violations"]["faculty_under_minimum_block"][f_idx]:
                    violation_list = results["violations"]["faculty_under_minimum_block"][f_idx][day_idx]
                    
                    for slot_idx, var in enumerate(violation_list):
                        deficiency_slots = solver.Value(var)
                        
                        if deficiency_slots > 0:
                            deficiency_mins = deficiency_slots * SLOT_SIZE
                            actual_block_mins = (MIN_BLOCK_SLOTS - deficiency_slots) * SLOT_SIZE
                            min_block_mins = MIN_BLOCK_SLOTS * SLOT_SIZE
                            
                            penalty = deficiency_slots * config["ConstraintPenalties"]["UNDER_MINIMUM_BLOCK_PER_SLOT"]
                            section_penalty += penalty
                            
                            day_name = config["SCHEDULING_DAYS"][day_idx][:3].capitalize()
                            faculty_name = faculty[f_idx].name
                            block_start_time = slot_to_time(slot_idx, config["DAY_START_MINUTES"])
                            
                            line = f"UNDER-MIN-BLOCK {faculty_name} ({day_name} {block_start_time}) " \
                                   f"short by {format_time_duration(deficiency_mins)} " \
                                   f"({format_time_duration(actual_block_mins)} < {format_time_duration(min_block_mins)}) " \
                                   f"[Penalty: {penalty}]"
                            violation_lines.append(line)
        
        # Batch under minimum blocks
        if "batch_under_minimum_block" in results["violations"]:
            for b_idx in results["violations"]["batch_under_minimum_block"]:
                for day_idx in results["violations"]["batch_under_minimum_block"][b_idx]:
                    violation_list = results["violations"]["batch_under_minimum_block"][b_idx][day_idx]
                    
                    for slot_idx, var in enumerate(violation_list):
                        deficiency_slots = solver.Value(var)
                        
                        if deficiency_slots > 0:
                            deficiency_mins = deficiency_slots * SLOT_SIZE
                            actual_block_mins = (MIN_BLOCK_SLOTS - deficiency_slots) * SLOT_SIZE
                            min_block_mins = MIN_BLOCK_SLOTS * SLOT_SIZE
                            
                            penalty = deficiency_slots * config["ConstraintPenalties"]["UNDER_MINIMUM_BLOCK_PER_SLOT"]
                            section_penalty += penalty
                            
                            day_name = config["SCHEDULING_DAYS"][day_idx][:3].capitalize()
                            batch_name = batches[b_idx].batch_id
                            block_start_time = slot_to_time(slot_idx, config["DAY_START_MINUTES"])
                            
                            line = f"UNDER-MIN-BLOCK {batch_name} ({day_name} {block_start_time}) " \
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

def run_two_pass_scheduler(config, subjects, rooms, faculty, batches, subjects_map,
                          seed, pass1_time, pass2_time, output_folder, deterministic_mode=False):
    """
    Run two-pass optimization: Pass 1 (structural) → Pass 2 (preferences).
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
        print("❌ Pass 1 failed! Cannot proceed to Pass 2.")
        return status_pass1, solver_pass1, results_pass1
    
    structural_minimum = results_pass1.get("pass1_structural_violations", 0)
    flush_print(f"\n✅ Pass 1 complete! Structural minimum: {structural_minimum}")
    
    # Save Pass 1 outputs
    flush_print("📄 Generating Pass 1 violation report...")
    try:
        pass1_violation_report_path = os.path.join(output_folder, "pass1_violation_report.txt")
        generate_violation_report(
            solver=solver_pass1,
            results=results_pass1,
            config=config,
            faculty=faculty,
            rooms=rooms,
            batches=batches,
            subjects_map=subjects_map,
            output_file=pass1_violation_report_path
        )
        flush_print(f"📄 Pass 1 violation report saved")
    except Exception as e:
        flush_print(f"⚠️ Error generating violation report: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
    
    flush_print("📊 Generating Pass 1 raw violations Excel...")
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
        flush_print(f"📊 Pass 1 raw violations saved")
    except Exception as e:
        flush_print(f"⚠️ Error generating raw violations: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
    
    # ============================================================================
    # EXPORT PASS 1 SOLUTION TO DATABASE
    # ============================================================================
    flush_print("💾 Exporting Pass 1 schedule to database...")
    try:
        pass1_db_path = os.path.join(output_folder, "pass1_schedule.db")
        save_schedule_with_full_view(status_pass1, solver_pass1, results_pass1, config, subjects, rooms, faculty, batches, db_path=pass1_db_path)
        flush_print(f"💾 Pass 1 schedule database saved to: {pass1_db_path}")
    except Exception as e:
        flush_print(f"⚠️ Error exporting Pass 1 to database: {e}")
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
    print("\n🧹 Cleaning up Pass 1 memory...")
    
    # Delete solver and results explicitly
    del solver_pass1
    del results_pass1
    
    # Force garbage collection multiple times to ensure all OR-Tools objects are released
    gc.collect()
    gc.collect()
    gc.collect()
    
    # Small delay to allow OS to reclaim memory
    time.sleep(0.5)
    
    print("✓ Memory cleanup complete")
    
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
        print("\n⚠️  Infeasible subject filtering is DISABLED")
        print("   Set FILTER_INFEASIBLE_SUBJECTS to true in config.json to enable\n")

    # ============ SEED CONFIGURATION ============
    # Set to True to use random seed search, False to use custom seed
    USE_RANDOM_SEED = False
    CUSTOM_SEED = 894646  # Used when USE_RANDOM_SEED = False
    is_deterministic_active = False
    # ============================================

    hour_time_limit = 0
    minute_time_limit = 25
    
    hour_time_seed = 0
    minute_time_seed = 25
    
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
    print(f"📁 Output folder: {output_folder}")

    if is_deterministic_active:
        print("Deterministic Mode Activated")
    else:
        print("Deterministic Mode De-activated")

    if USE_RANDOM_SEED:
        # ============================================================================
        # SEED SEARCH MODE: Try multiple seeds and keep the best
        # ============================================================================
        print("🎲 Running with RANDOM SEED SEARCH")
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
                print(f"\n⏰ Total time limit reached ({total_time_limit_input}s)")
                break
            
            seed = random.randint(0, 999999)
            seeds_tried += 1
            print(f"\n🔍 Attempt {seeds_tried}/{num_seeds_input} - Seed: {seed}")
            
            # Create subfolder for this seed
            seed_folder = os.path.join(output_folder, f"seed_{seed}")
            os.makedirs(seed_folder, exist_ok=True)
            
            # Run two-pass optimization (EXACT same logic as non-seed search)
            status, solver, results = run_two_pass_scheduler(
                config, subjects, rooms, faculty, batches, subjects_map,
                seed=seed,
                pass1_time=pass1_time_per_seed,
                pass2_time=pass2_time_per_seed*0,
                output_folder=seed_folder,
                deterministic_mode=is_deterministic_active
            )
            
            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                penalty = solver.ObjectiveValue()
                print(f"   ✅ Solution found - Penalty: {penalty}")
                
                # Save full outputs for this seed
                violation_report_path = os.path.join(seed_folder, "violation_report.txt")
                generate_violation_report(
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
                
                print(f"   📁 Outputs saved to: {seed_folder}")
                
                # Track best solution
                if penalty < best_penalty:
                    best_penalty = penalty
                    best_solution = (status, solver, results)
                    best_seed = seed
                    print(f"   🌟 NEW BEST SOLUTION! (Penalty: {penalty})")
            else:
                print(f"   ❌ No solution found")
        
        print("\n" + "=" * 70)
        if best_solution:
            status, solver, results = best_solution
            print(f"✅ Seed search complete!")
            print(f"   Best seed: {best_seed}")
            print(f"   Best penalty: {best_penalty}")
            print(f"   Seeds tried: {seeds_tried}")
            print(f"   Best solution: {os.path.join(output_folder, f'seed_{best_seed}')}")
        else:
            print("❌ No feasible solution found during seed search.")
            status, solver, results = None, None, None
    else:
        # ============================================================================
        # SINGLE SEED MODE: Run with custom seed
        # ============================================================================
        print(f"🎯 Running with CUSTOM SEED: {CUSTOM_SEED}")
        
        # Time allocation (30% Pass 1, 70% Pass 2 - same as seed search)
        pass1_time = int(total_time_limit_input * 1)
        pass2_time = total_time_limit_input 
        """ - pass1_time """
        
        # Run two-pass optimization (EXACT same function as seed search uses)
        status, solver, results = run_two_pass_scheduler(
            config, subjects, rooms, faculty, batches, subjects_map,
            seed=CUSTOM_SEED,
            pass1_time=pass1_time,
            pass2_time=pass2_time*0,
            output_folder=output_folder,
            deterministic_mode=is_deterministic_active
        )

    # ============================================================================
    # SAVE FINAL OUTPUTS (for both seed search and single seed modes)
    # ============================================================================
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Save violation report to output folder
        violation_report_path = os.path.join(output_folder, "violation_report.txt")
        generate_violation_report(
            solver=solver,
            results=results,
            config=config,
            faculty=faculty,
            rooms=rooms,
            batches=batches,
            subjects_map=subjects_map,
            output_file=violation_report_path
        )
        print(f"\n✅ Violation report saved to: {violation_report_path}")

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
        save_schedule_with_full_view(status, solver, results, config, subjects, rooms, faculty, batches, db_path=db_path)
        
        print(f"\n📁 All outputs saved to: {output_folder}")
    else:
        print("\n❌ No feasible solution found. No outputs generated.")