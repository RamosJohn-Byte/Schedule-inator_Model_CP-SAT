"""
Universal Controller Debug Exporter

Routes debug exports to the appropriate controller-specific exporter based on controller type.
"""

from timeslot_system.ghostblock import export_ghostblock_debug


def export_controller_debug(controller_data, solver, faculty, batches, config, 
                           streak_data, output_dir=None, pass_name=""):
    """
    Universal debug export function that routes to controller-specific exporters.
    
    Detects which controller was used and calls the appropriate debug function.
    
    Args:
        controller_data: Dictionary returned by controller with 'controller_type' key
        solver: Solved CP-SAT solver instance
        faculty: List of Faculty objects
        batches: List of Batch objects
        config: Configuration dictionary
        streak_data: Dictionary from streak_tracker containing streak variables
        output_dir: Directory to save debug files
        pass_name: Label for this debug export (e.g., "Pass_1", "Final")
    
    Supported Controllers:
        - 'ghostblock': Ghost Block Controller (uses ghost_active variables)
        - 'slot_oracle': Slot Oracle Controller (uses coverage detection)
    """
    
    controller_type = controller_data.get('controller_type', 'unknown')
    
    if controller_type == 'ghostblock':
        print(f"[Controller Debug] Detected Ghost Block Controller - exporting ghost grid...")
        export_ghostblock_debug(
            controller_data=controller_data,
            solver=solver,
            faculty=faculty,
            batches=batches,
            config=config,
            streak_data=streak_data,
            output_dir=output_dir,
            pass_name=pass_name
        )
    
    elif controller_type == 'slot_oracle':
        print(f"[Controller Debug] Detected Slot Oracle Controller")
        print(f"   ⚠️  Slot Oracle debug export not yet implemented (controller still WIP)")
        # TODO: Create export_slot_oracle_debug() once controller is stable
        # export_slot_oracle_debug(controller_data, solver, faculty, batches, config, ...)
    
    else:
        print(f"⚠️  [Controller Debug] Unknown controller type: '{controller_type}'")
        print(f"   No debug export performed. Valid types: 'ghostblock', 'slot_oracle'")
