"""scheduler.py - run one of these scripts automatically on a schedule.

Point SCRIPT at any script in this folder and pick a schedule: every N minutes, or
once a day at a set time. This process re-launches it on that schedule for as long
as it stays open (Ctrl+C to stop). Cross-platform, standard library only.

For truly unattended scheduling (survives closing the window and reboots), use the
OS scheduler instead: Windows Task Scheduler, or cron on macOS/Linux (see the
"Running on a schedule" section of the README). This is the simple "leave it
running" option.

Setup:
    # nothing to install (standard library only)
    python scheduler.py
"""

GUI = True  # show this script in the Automation GUI window

# ================= CONFIG - edit these, then run =================
SCRIPT = "web_search.py"  # a script in this folder to run on the schedule

MODE = "interval"  # "interval" | "daily"
EVERY_MINUTES = 60  # interval mode: minutes between runs
AT_TIME = "08:00"  # daily mode: time of day, 24-hour HH:MM
RUN_AT_START = True  # interval mode: also run once immediately when started
# ================================================================

import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


def run_once() -> None:
    script_path = Path(__file__).with_name(SCRIPT)
    if not script_path.is_file():
        sys.exit(f"SCRIPT not found next to scheduler.py: {SCRIPT}")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] running {SCRIPT} ...")
    subprocess.run([sys.executable, str(script_path)])


def seconds_until(at_time: str) -> float:
    now = datetime.now()
    hh, mm = (int(x) for x in at_time.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main() -> None:
    print(f"Scheduler started ({MODE}). Ctrl+C to stop.\n")
    try:
        if MODE == "interval":
            if RUN_AT_START:
                run_once()
            while True:
                print(f"  sleeping {EVERY_MINUTES} min ...")
                time.sleep(EVERY_MINUTES * 60)
                run_once()
        elif MODE == "daily":
            while True:
                wait = seconds_until(AT_TIME)
                print(f"  next run at {AT_TIME} (in {wait / 3600:.1f} h) ...")
                time.sleep(wait)
                run_once()
        else:
            sys.exit(f"Unknown MODE: {MODE!r} (use 'interval' or 'daily')")
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
