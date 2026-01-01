# utils.py
"""
Utility functions used across the scheduling system.
"""

import os
import sys
from datetime import datetime


def flush_print(*args, **kwargs):
    """Enable immediate output flushing for debugging hangs."""
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
    """Load configuration from JSON file."""
    import json
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"FATAL: Could not load or parse {path}. Error: {e}")
        exit(1)
