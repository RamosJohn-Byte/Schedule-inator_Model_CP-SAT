# export_db.py
"""
Database export functions for saving schedule results to SQLite.
"""

import os
import sqlite3
from ortools.sat.python import cp_model


def save_schedule_to_db(status, solver, results, config, subjects, rooms, faculty, batches, subjects_map, db_path=None):
    """
    Save the schedule to a SQLite database with normalized tables.
    
    Args:
        status: Solver status code
        solver: CpSolver instance with solution
        results: Dictionary from run_scheduler containing all variables
        config: Configuration dictionary
        subjects: List of Subject objects
        rooms: List of Room objects
        faculty: List of Faculty objects
        batches: List of Batch objects
        subjects_map: Dictionary mapping subject_id to Subject objects
        db_path: Path to save the database (default: outputs/schedule.db)
    """
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


def save_schedule_with_full_view(status, solver, results, config, subjects, rooms, faculty, batches, subjects_map, db_path=None):
    """
    Save the schedule to a SQLite database with normalized tables AND denormalized full view.
    Includes external meetings in the output.
    
    Args:
        status: Solver status code
        solver: CpSolver instance with solution
        results: Dictionary from run_scheduler containing all variables
        config: Configuration dictionary
        subjects: List of Subject objects
        rooms: List of Room objects
        faculty: List of Faculty objects
        batches: List of Batch objects
        subjects_map: Dictionary mapping subject_id to Subject objects
        db_path: Path to save the database (default: outputs/schedule.db)
    """
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
