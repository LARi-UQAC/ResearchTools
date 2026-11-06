"""
batch_stats - Batch statistics and loop counter for work-ugs-audit.

Purpose:
    Decides if the batch is in the calibration band, manages the loop counter,
    writes the grades CSV, and renders the batch report.

Details:
    - Uses sample standard deviation (n-1).
    - Reads thresholds from targets dict (derived from configuration).
    - Never prints comment text in the JSON output line.

Inputs:
    - totals: list of dicts with report_id, percent, complete.
    - targets: dict with target_mean, target_sd, mean_tolerance, sd_tolerance, max_loops.
    - outlier_z: float threshold for z-score.

Outputs:
    - analyze: dict with n, mean, sd, bands, verdict, reasons, outliers, excluded.
    - next_loop: int (new loop number).
    - write_grades_csv: writes CSV file.
    - render_report: str (rendered report).
    - main: CLI entry point.
"""

import argparse
import json
import sys
from pathlib import Path
from string import Template
from statistics import mean, stdev

class LoopLimit(RuntimeError):
    """Raised when the loop limit is exceeded."""
    pass

def analyze(totals: list[dict], targets: dict, outlier_z: float) -> dict:
    """
    Purpose: Calculate batch statistics and determine if the batch is in band.
    Inputs:
        totals: List of report totals dicts.
        targets: Dict with calibration targets.
        outlier_z: Z-score threshold for outliers.
    Outputs:
        Dict with statistics and verdict.
    """
    # Filter out incomplete reports
    complete_totals = [t for t in totals if t.get("complete")]
    excluded_ids = [t["report_id"] for t in totals if not t.get("complete")]
    
    n = len(complete_totals)
    
    if n < 2:
        return {
            "n": n,
            "mean": None,
            "sd": None,
            "mean_band": [None, None],
            "sd_band": [None, None],
            "verdict": "insufficient",
            "reasons": ["Insufficient reports (n < 2)"],
            "outliers": [],
            "excluded": excluded_ids
        }

    percents = [t["percent"] for t in complete_totals]
    m = mean(percents)
    sd = stdev(percents) # Sample standard deviation

    target_mean = targets["target_mean"]
    target_sd = targets["target_sd"]
    mean_tol = targets["mean_tolerance"]
    sd_tol = targets["sd_tolerance"]

    mean_band = [target_mean - mean_tol, target_mean + mean_tol]
    sd_band = [target_sd - sd_tol, target_sd + sd_tol]

    reasons = []
    in_band = True

    if m < mean_band[0] or m > mean_band[1]:
        in_band = False
        reasons.append(f"mean {m} outside band {mean_band}")

    if sd < sd_band[0] or sd > sd_band[1]:
        in_band = False
        reasons.append(f"sd {sd} outside band {sd_band}")

    # Calculate outliers
    outliers = []
    if sd > 0:
        for t in complete_totals:
            z = (t["percent"] - m) / sd
            if abs(z) > outlier_z:
                outliers.append(t["report_id"])
    else:
        # If sd is 0, no outliers unless we define them differently, but usually 0 sd means all same
        # The spec says "ids whose absolute z-score exceeds outlier_z". If sd=0, z is undefined or 0.
        # We'll assume no outliers if sd=0 to avoid division by zero.
        pass

    verdict = "in_band" if in_band else "out_of_band"

    return {
        "n": n,
        "mean": m,
        "sd": sd,
        "mean_band": mean_band,
        "sd_band": sd_band,
        "verdict": verdict,
        "reasons": reasons,
        "outliers": outliers,
        "excluded": excluded_ids
    }

def next_loop(state_path: Path, max_loops: int, allow_third: bool) -> int:
    """
    Purpose: Manage the loop counter state.
    Inputs:
        state_path: Path to the JSON state file.
        max_loops: Maximum allowed loops.
        allow_third: If True, allows exceeding max_loops (specifically for the 3rd loop).
    Outputs:
        int: The new loop number.
    Raises:
        LoopLimit: If max_loops is exceeded and allow_third is False.
    """
    current = 0
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            current = data.get("loop", 0)
        except json.JSONDecodeError:
            current = 0

    next_num = current + 1

    if next_num > max_loops and not allow_third:
        raise LoopLimit(f"Loop limit {max_loops} exceeded")

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"loop": next_num}), encoding="utf-8")
    
    return next_num

def write_grades_csv(totals: list[dict], rubric: dict, path: Path) -> None:
    """
    Purpose: Write the grades table to a CSV file.
    Inputs:
        totals: List of report totals dicts.
        rubric: Dict with rubric items.
        path: Path to the output CSV file.
    Outputs:
        None.
    """
    item_ids = [item["id"] for item in rubric.get("items", [])]
    
    header = ["report_id"] + item_ids + ["total", "percent", "complete"]
    
    lines = [",".join(header)]
    
    for t in totals:
        row = [t["report_id"]]
        for iid in item_ids:
            score = t.get("by_item", {}).get(iid, "")
            row.append(str(score))
        
        row.append(str(t.get("total", "")))
        row.append(str(t.get("percent", "")))
        row.append(str(t.get("complete", "")))
        
        lines.append(",".join(row))
    
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def render_report(values: dict, template_text: str) -> str:
    """
    Purpose: Render the batch report using a string template.
    Inputs:
        values: Dict with values to substitute.
        template_text: The template string.
    Outputs:
        str: The rendered report.
    Raises:
        KeyError: If a key is missing in values.
    """
    # string.Template raises ValueError on missing keys if we don't check, 
    # but the spec says "a missing key raises". 
    # Actually, Template.substitute raises KeyError if a key is missing.
    # Let's verify: 
    # >>> from string import Template
    # >>> t = Template("$a $b")
    # >>> t.substitute(a=1)
    # KeyError: 'b'
    
    return Template(template_text).substitute(values)

def main(argv=None):
    """
    Purpose: CLI entry point for batch_stats.
    Inputs:
        argv: List of command line arguments.
    Outputs:
        None.
    """
    parser = argparse.ArgumentParser(description="Batch statistics for work-ugs-audit")
    parser.add_argument("--work", required=True, help="Work directory")
    parser.add_argument("--loop", type=int, required=True, help="Loop number")
    parser.add_argument("--type", required=True, choices=["lab_report", "project_report"], help="Assessment type")
    parser.add_argument("--allow-third", action="store_true", help="Allow third loop")
    parser.add_argument("--next-loop", action="store_true", help="Only update loop counter")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    
    args = parser.parse_args(argv)
    
    work_dir = Path(args.work).resolve()
    
    if args.next_loop:
        state_path = work_dir / "loop_state.json"
        try:
            # We need max_loops from config or targets. 
            # For now, assuming we load it or use a default from config.
            # The plan says "reads ... the targets file of the skill".
            # But next_loop signature takes max_loops.
            # Let's assume we load config to get max_loops.
            
            # Load config
            config_path = Path(__file__).resolve().parent.parent / "assets" / "ugs_config.json"
            # We don't have ugs_config imported here easily without circular deps or path issues.
            # Let's just hardcode the path to calibration targets for max_loops?
            # No, max_loops is in calibration_targets.json.
            
            targets_path = Path(__file__).resolve().parent.parent / "assets" / "calibration_targets.json"
            targets_data = json.loads(targets_path.read_text(encoding="utf-8"))
            max_loops = targets_data[args.type]["max_loops"]["value"]
            
            new_loop = next_loop(state_path, max_loops, args.allow_third)
            print(new_loop)
            return 0
        except LoopLimit:
            print("Refusal: Loop limit exceeded", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"Failure: {e}", file=sys.stderr)
            return 1

    # Normal batch stats flow
    loop_dir = work_dir / f"loop-{args.loop}"
    
    # Find report folders R*
    report_folders = [d for d in loop_dir.iterdir() if d.is_dir() and d.name.startswith("R")]
    
    totals = []
    for rf in report_folders:
        totals_file = rf / "totals.json"
        if totals_file.exists():
            try:
                t = json.loads(totals_file.read_text(encoding="utf-8"))
                totals.append(t)
            except json.JSONDecodeError:
                pass # Skip malformed
    
    if not totals:
        print("Refusal: No totals found", file=sys.stderr)
        return 2

    # Load rubric
    rubric_file = work_dir / "rubric.json"
    if not rubric_file.exists():
        print("Refusal: Rubric not found", file=sys.stderr)
        return 2
    rubric = json.loads(rubric_file.read_text(encoding="utf-8"))

    # Load targets
    targets_path = Path(__file__).resolve().parent.parent / "assets" / "calibration_targets.json"
    targets_data = json.loads(targets_path.read_text(encoding="utf-8"))
    targets = {
        "target_mean": targets_data[args.type]["target_mean"]["value"],
        "target_sd": targets_data[args.type]["target_sd"]["value"],
        "mean_tolerance": targets_data[args.type]["mean_tolerance"]["value"],
        "sd_tolerance": targets_data[args.type]["sd_tolerance"]["value"],
        "max_loops": targets_data[args.type]["max_loops"]["value"]
    }
    
    # Load outlier_z from config
    config_path = Path(__file__).resolve().parent.parent / "assets" / "ugs_config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        outlier_z = config["batch.outlier_z"]["value"]
    except (json.JSONDecodeError, KeyError):
        outlier_z = 2.0 # Fallback, though R0 says no hardcoded. We should fail.
        print("Refusal: Missing batch.outlier_z in config", file=sys.stderr)
        return 2

    result = analyze(totals, targets, outlier_z)
    
    # Write CSV
    csv_path = loop_dir / "grades.csv"
    write_grades_csv(totals, rubric, csv_path)
    
    # Render report
    template_path = Path(__file__).resolve().parent.parent / "assets" / "batch_report.template.md"
    if not template_path.exists():
        # If template is missing, we can't render. 
        # The plan says "writes ... the file named batch_report".
        # It implies a template exists or we generate it.
        # The plan says "render_report(values, template_text)".
        # Let's assume a template file exists.
        print("Refusal: Template not found", file=sys.stderr)
        return 2
        
    template_text = template_path.read_text(encoding="utf-8")
    
    report_values = {
        "loop": args.loop,
        "assessment_type": args.type,
        "n": result["n"],
        "mean": result["mean"],
        "mean_band": result["mean_band"],
        "sd": result["sd"],
        "sd_band": result["sd_band"],
        "verdict": result["verdict"],
        "reasons": "; ".join(result["reasons"]),
        "outlier_z": outlier_z,
        "outliers": ", ".join(result["outliers"]),
        "excluded": ", ".join(result["excluded"])
    }
    
    try:
        report_text = render_report(report_values, template_text)
    except KeyError as e:
        print(f"Refusal: Missing key in report values: {e}", file=sys.stderr)
        return 2

    report_path = loop_dir / "batch_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    
    # Print JSON line
    output = {
        "verdict": result["verdict"],
        "n": result["n"],
        "mean": result["mean"],
        "sd": result["sd"],
        "mean_band": result["mean_band"],
        "sd_band": result["sd_band"],
        "reasons": result["reasons"],
        "outliers": result["outliers"],
        "excluded": result["excluded"]
    }
    print(json.dumps(output))
    
    if result["verdict"] == "in_band":
        return 0
    else:
        return 3

if __name__ == "__main__":
    sys.exit(main())
