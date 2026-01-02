"""
Solver callback for logging intermediate solutions during optimization.
"""

import time
import os
from datetime import datetime
from ortools.sat.python import cp_model


class SolutionPrinterCallback(cp_model.CpSolverSolutionCallback):
    """Prints intermediate solutions with progress metrics and logs to file."""

    def __init__(self, total_penalty, log_file_path=None):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self.__solution_count = 0
        self.__total_penalty = total_penalty
        self.__previous_penalty = None
        self.__last_solution_time = None
        self.__start_time = time.time()
        self.__log_file_path = log_file_path
        # Track solver statistics over time
        self.__last_branches = 0
        self.__last_conflicts = 0
        self.__stats_history = []  # List of (time, branches, conflicts, penalty, gap)

        if self.__log_file_path:
            os.makedirs(os.path.dirname(self.__log_file_path), exist_ok=True)
            with open(self.__log_file_path, "w", encoding="utf-8") as log_file:
                log_file.write("=== Solution Log ===\n")
                log_file.write(f"Started: {datetime.now().isoformat()}\n")
                log_file.write("--------------------\n")

    def on_solution_callback(self):
        self.__solution_count += 1
        current_penalty = self.Value(self.__total_penalty)
        current_time = time.time()
        
        elapsed_total = current_time - self.__start_time
        
        # Get current solver statistics
        current_branches = self.NumBranches()
        current_conflicts = self.NumConflicts()
        current_bound = self.BestObjectiveBound()
        current_gap = abs(current_penalty - current_bound) if current_bound else 0
        gap_percent = (current_gap / max(abs(current_penalty), 1)) * 100 if current_penalty != 0 else 0
        
        hours = int(elapsed_total // 3600)
        minutes = int((elapsed_total % 3600) // 60)
        seconds = int(elapsed_total % 60)

        time_parts = []
        if hours > 0:
            time_parts.append(f"{hours}h")
        if minutes > 0:
            time_parts.append(f"{minutes}m")
        time_parts.append(f"{seconds}s")  # always show seconds

        elapsed_str = " ".join(time_parts)

        output = f"Solution {self.__solution_count}, penalty = {current_penalty}, time = {elapsed_str}"
        
        # Calculate delta statistics since last solution
        delta_branches = current_branches - self.__last_branches
        delta_conflicts = current_conflicts - self.__last_conflicts
        
        if self.__previous_penalty is not None and self.__last_solution_time is not None:
            penalty_decrease = self.__previous_penalty - current_penalty
            time_diff = current_time - self.__last_solution_time
            ratio = penalty_decrease / time_diff if time_diff > 0 else 0
            branches_per_sec = delta_branches / time_diff if time_diff > 0 else 0
            conflicts_per_sec = delta_conflicts / time_diff if time_diff > 0 else 0
            output += f' (down {penalty_decrease} in {time_diff:.1f}s, ratio: {ratio:.1f}/s)'
            output += f' | br/s: {branches_per_sec:,.0f}, cf/s: {conflicts_per_sec:,.0f}, gap: {gap_percent:.1f}%'
        else:
            output += f' | gap: {gap_percent:.1f}%'
        
        print(output)

        if self.__log_file_path:
            with open(self.__log_file_path, "a", encoding="utf-8") as log_file:
                log_file.write(output + "\n")
        
        # Store statistics for analysis
        self.__stats_history.append({
            'time': elapsed_total,
            'solution': self.__solution_count,
            'penalty': current_penalty,
            'gap': current_gap,
            'gap_percent': gap_percent,
            'total_branches': current_branches,
            'total_conflicts': current_conflicts,
            'delta_branches': delta_branches,
            'delta_conflicts': delta_conflicts,
        })

        self.__previous_penalty = current_penalty
        self.__last_solution_time = current_time
        self.__last_branches = current_branches
        self.__last_conflicts = current_conflicts

    def solution_count(self):
        return self.__solution_count
    
    def get_stats_history(self):
        """Return the statistics history for post-solve analysis."""
        return self.__stats_history
    
    def write_stats_summary(self, output_path=None):
        """Write a summary of solver statistics over time to file."""
        if not self.__stats_history:
            return
        
        path = output_path or (self.__log_file_path.replace('.txt', '_stats.txt') if self.__log_file_path else 'solver_stats.txt')
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write("=" * 120 + "\n")
            f.write("SOLVER STATISTICS OVER TIME\n")
            f.write("=" * 120 + "\n\n")
            
            f.write(f"{'Sol#':>5} | {'Time':>8} | {'Penalty':>10} | {'Gap%':>7} | {'Δ Branches':>12} | {'Δ Conflicts':>12} | {'Br/s':>10} | {'Cf/s':>10}\n")
            f.write("-" * 120 + "\n")
            
            prev_time = 0
            for s in self.__stats_history:
                time_diff = s['time'] - prev_time
                br_per_sec = s['delta_branches'] / time_diff if time_diff > 0 else 0
                cf_per_sec = s['delta_conflicts'] / time_diff if time_diff > 0 else 0
                
                f.write(f"{s['solution']:>5} | {s['time']:>7.1f}s | {s['penalty']:>10,} | {s['gap_percent']:>6.1f}% | {s['delta_branches']:>12,} | {s['delta_conflicts']:>12,} | {br_per_sec:>10,.0f} | {cf_per_sec:>10,.0f}\n")
                prev_time = s['time']
            
            f.write("\n" + "=" * 120 + "\n")
            f.write("PHASE ANALYSIS\n")
            f.write("=" * 120 + "\n\n")
            
            # Analyze phases by branch rate
            early = [s for s in self.__stats_history if s['time'] < 120]  # First 2 min
            mid = [s for s in self.__stats_history if 120 <= s['time'] < 300]  # 2-5 min
            late = [s for s in self.__stats_history if s['time'] >= 300]  # 5+ min
            
            def avg_rate(stats, key):
                if not stats or len(stats) < 2:
                    return 0
                total_delta = sum(s[key] for s in stats[1:])  # Skip first (no delta)
                total_time = stats[-1]['time'] - stats[0]['time']
                return total_delta / total_time if total_time > 0 else 0
            
            f.write(f"Early phase (0-2min):   {len(early):>3} solutions, avg {avg_rate(early, 'delta_branches'):>10,.0f} br/s, {avg_rate(early, 'delta_conflicts'):>10,.0f} cf/s\n")
            f.write(f"Middle phase (2-5min):  {len(mid):>3} solutions, avg {avg_rate(mid, 'delta_branches'):>10,.0f} br/s, {avg_rate(mid, 'delta_conflicts'):>10,.0f} cf/s\n")
            f.write(f"Late phase (5min+):     {len(late):>3} solutions, avg {avg_rate(late, 'delta_branches'):>10,.0f} br/s, {avg_rate(late, 'delta_conflicts'):>10,.0f} cf/s\n")
            
            # Identify slowdown patterns
            f.write("\n" + "-" * 120 + "\n")
            f.write("SLOWDOWN INDICATORS:\n")
            
            if late and early:
                early_rate = avg_rate(early, 'delta_branches')
                late_rate = avg_rate(late, 'delta_branches')
                if early_rate > 0 and late_rate > 0:
                    slowdown = early_rate / late_rate
                    f.write(f"   Branch rate slowdown: {slowdown:.1f}x slower in late phase\n")
                    
                    if slowdown > 10:
                        f.write("   [CRITICAL] Severe slowdown - likely hitting propagation bottleneck\n")
                    elif slowdown > 3:
                        f.write("   [WARNING] Significant slowdown - solver struggling with harder subproblems\n")
                    else:
                        f.write("   [OK] Normal slowdown as search space narrows\n")
            
            # Check for plateau (many solutions with small improvements)
            if len(self.__stats_history) > 10:
                last_10 = self.__stats_history[-10:]
                avg_improvement = sum(
                    (last_10[i-1]['penalty'] - last_10[i]['penalty']) 
                    for i in range(1, len(last_10))
                ) / (len(last_10) - 1)
                time_span = last_10[-1]['time'] - last_10[0]['time']
                
                f.write(f"\n   Last 10 solutions: avg improvement {avg_improvement:.0f} over {time_span:.0f}s\n")
                if avg_improvement < 100 and time_span > 60:
                    f.write("   [WARNING] Plateau detected - small improvements taking long time\n")
                    f.write("   Consider: symmetry breaking, LNS parameters, or objective decomposition\n")
        
        print(f"[Stats] Detailed statistics written to: {path}")
