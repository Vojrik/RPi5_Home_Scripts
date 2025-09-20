DISK CHECKS – Documentation and Schedule
=======================================

Quick Overview (what runs, when, and where it logs)
--------------------------------------------------
- Daily 19:00: SMART quick scan + RAID watch
  - Cron: `0 19 * * *`
  - Logs: `/var/log/Disck_checks/smart_daily.log`, `/var/log/Disck_checks/raid_watch.log`
- Weekly (Tuesday) 17:50: short SMART self-tests
  - Cron: `50 17 * * 2`
  - Log: `/var/log/Disck_checks/smart_daily.log`
- Monthly (first Tuesday) 08:00: RAID parity check (`check` action)
  - Cron: `0 8 * * 2 [ $(date +%d) -le 7 ] && …`
  - Log: `/var/log/Disck_checks/raid_check.log`
- Monthly (first Tuesday) 18:30: long SMART self-tests
  - Cron: `30 18 * * 2 [ $(date +%d) -le 7 ] && …`
  - Log: `/var/log/Disck_checks/smart_daily.log`

Desktop shortcuts point to the active log files with matching names.

Current Cron Schedule
---------------------
- Daily checks (19:00)
  - Sequentially: SMART quick scan (no self-tests) → RAID watch
  - Cron (root):
    `0 19 * * * nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/smart_daily.sh >/tmp/smart_daily.cron.log 2>&1; nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/raid_watch.sh >/tmp/raid_watch.cron.log 2>&1`
- Weekly short SMART self-tests (Tuesday 17:50)
  - Cron (root):
    `50 17 * * 2 nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/smart_daily.sh --short >/tmp/smart_short.cron.log 2>&1`
  - Skipped automatically if it is the first Tuesday of the month (long tests run later that day).
- Monthly long SMART self-tests (first Tuesday 18:30)
  - Cron (root):
    `30 18 * * 2 [ $(date +\%d) -le 7 ] && nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/smart_daily.sh --long >/tmp/smart_long.cron.log 2>&1`
- RAID parity check (first Tuesday 08:00, scheduled during daytime)
  - Cron (root):
    `0 8 * * 2 [ $(date +\%d) -le 7 ] && nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/raid_check.sh >/tmp/raid_check.cron.log 2>&1`

Cron treats the day-of-month and day-of-week fields as logical OR, hence the `[ $(date +%d) -le 7 ]` guard.

Script Overview
---------------
1) `smart_daily.sh`
   - Purpose: daily SMART health check with optional short/long self-tests.
   - Behaviour:
     - Skips the root disk; checks NVMe and SATA/USB disks.
     - Collects SMART health, attributes, error logs, and lifetime counters.
     - Detects long-running tests (short >2h, long >24h) and raises alerts.
     - Sends email on issues; logs to `/var/log/Disck_checks/smart_daily.log`.
     - Options: `--short`, `--long`, `--dry-run`, `--wait`, `--abort-running`.
2) `raid_watch.sh`
   - Purpose: daily mdraid health check.
   - Reads `/proc/mdstat`, `mdadm --detail /dev/mdX`, and member states in `/sys/block/mdX/md/dev-*/state`.
   - Sends email if degraded, missing members, or failed devices.
   - Logs to `/var/log/Disck_checks/raid_watch.log`.
3) `raid_check.sh`
   - Purpose: monthly parity check with mismatch reporting.
   - Runs `echo check > /sys/block/mdX/md/sync_action`, waits for completion, reports `mismatch_cnt`.
   - Sends email when mismatches are found; suggests running `echo repair ...`.
   - Logs to `/var/log/Disck_checks/raid_check.log`.

Problem Criteria (SMART)
------------------------
- Non-zero SMART return code (rc & 2)
- Reallocated, pending, or offline-uncorrectable sectors greater than zero
- Self-test status "in progress" beyond 2h (short) or 24h (long)
- Critical temperature, media wearout (for NVMe) reported by smartctl

Problem Criteria (RAID)
-----------------------
- Array state contains `degraded`
- Failed devices count > 0
- Active devices fewer than expected
- Member state not `in_sync`

Parity Check (`raid_check.sh`)
------------------------------
- After `check`, inspect `mismatch_cnt`:
  - >0 → send email recommending `echo repair > /sys/block/<mdX>/md/sync_action`
  - 0  → no email

Logs and Shortcuts
------------------
- Primary location: `/var/log/Disck_checks`
- Fallback when run manually without sudo: `~/Disck_checks/logs`
- Desktop symlinks: `smart_daily.log`, `raid_watch.log`, `raid_check.log`
- Logs owned by `vojrik:vojrik` for easy access

Cron Notes
----------
- `/etc/cron.d/mdadm` entries for these jobs have been disabled (`DISABLED (replaced by root crontab)`).

Email Notifications
-------------------
- Outbound mail via msmtp (`/home/vojrik/Scripts/Disck_checks/.msmtprc`)
- Recipient: `Vojta.Hamacek@seznam.cz`
- Subjects:
  - SMART: `[SMART ALERT] <hostname> – issues detected`
  - RAID : `[RAID ALERT]  <hostname> – problem detected` / `– parity mismatches`
- Body includes summary + full log for diagnostics

Manual Execution
----------------
- Daily SMART check: `sudo /home/vojrik/Scripts/Disck_checks/smart_daily.sh`
- Short tests: `sudo .../smart_daily.sh --short`
- Long tests: `sudo .../smart_daily.sh --long`
- Dry run: `sudo .../smart_daily.sh --dry-run [--short|--long]`
- RAID check: `sudo /home/vojrik/Scripts/Disck_checks/raid_check.sh &`
  - Track progress: `cat /proc/mdstat | grep -i check`
  - Safe stop: `sudo pkill -INT -f /home/vojrik/Scripts/Disck_checks/raid_check.sh`

Requirements and Notes
----------------------
- Packages: `smartmontools`, `mdadm`, `hdparm`, `msmtp`
- Cron runs as root (full access to `/sys` and smartctl)
- Scripts use `nice` and `ionice` when scheduled
- `loop` and `zram` devices are ignored
- Self-tests execute asynchronously; results show up in subsequent smartctl outputs
