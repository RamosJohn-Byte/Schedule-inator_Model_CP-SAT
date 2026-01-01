# data_models.py
from dataclasses import dataclass, field
from typing import List, Set

@dataclass
class Program:
    program_id: str
    program_name: str
    row_id: int = None

@dataclass
class RoomType:
    """Lookup table for room types (from room_types.csv)"""
    id: int
    name: str
    description: str = None

@dataclass
class SubjectType:
    """Lookup table for subject types (from subject_types.csv)"""
    id: int
    name: str
    description: str = None

@dataclass
class Room:
    room_id: str
    capacity: int
    room_type_id: int  # Foreign key to RoomType.id
    row_id: int = None

@dataclass
class Faculty:
    id: str
    name: str
    max_hours: int  # Computed from max_load * 3
    min_hours: int  # Computed from min_load * 3
    qualified_subject_ids: Set[int] = field(default_factory=set)  # Set of subject IDs (integers)
    preferred_subject_ids: Set[int] = field(default_factory=set)  # Set of subject IDs (integers)
    max_subjects: int = None
    row_id: int = None

@dataclass
class Subject:
    subject_id: int  # Primary key (from id column)
    subject_code: str  # Display name (from subject_code column)
    required_weekly_minutes: int
    ideal_num_sections: int
    enrolling_batch_ids: List[str] = field(default_factory=list)
    subject_type_id: int = None  # Foreign key to SubjectType.id
    linked_subject_id: int = None  # Foreign key to another Subject.id
    room_type_id: int = None  # Foreign key to RoomType.id
    max_enrollment: int = None
    min_enrollment: int = None
    min_meetings: int = None  # Minimum number of meetings per week
    max_meetings: int = None  # Maximum number of meetings per week
    row_id: int = None

@dataclass
class BannedTime:
    day_index: int
    start_slot: int
    end_slot: int

@dataclass
class TimeBlock:  
    day_index: int
    start_minutes: int 
    end_minutes: int

@dataclass
class ExternalMeeting:
    day_index: int
    start_minutes: int
    end_minutes: int
    event_name: str
    description: str

@dataclass
class Batch:
    batch_id: str
    program_id: str
    population: int
    subjects: List[Subject] = field(default_factory=list)
    banned_times: List[BannedTime] = field(default_factory=list)
    external_meetings: List[ExternalMeeting] = field(default_factory=list)
    row_id: int = None