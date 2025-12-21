# Review of the RPi5 Home Main Repository

## Status Summary
- The modular installer `install_rpi5_home.sh` is clear and uses shared helpers from `install_modules/lib.sh`, so the core installation flow is consistent.
- The repository includes dedicated script directories (Backup, CPU_freq, Fan, home-automation-backup, etc.) deployed via `deploy_scripts.sh` and covering the main home automation functions.
- Some installation steps are not idempotent (overclock block, docker stack) and part of the fallback logic is destructive (`rm -rf`), so repeated runs can lead to an inconsistent state.

## Positive Findings
- All modular scripts in `install_modules/` use `set -Eeuo pipefail` and shared logging helpers, which reduces the risk of silent failures.【F:install_rpi5_home.sh†L1-L41】【F:install_modules/lib.sh†L1-L64】
- The base installation is composed of clear steps (overclock, OS update, package installation, script deployment), and users can skip or repeat them as needed.【F:install_rpi5_home.sh†L11-L40】
- The `Backup/rpi_backup_pishrink.sh` script stops containers before creating the image and starts them again afterward, keeping backups consistent.【F:Backup/rpi_backup_pishrink.sh†L106-L154】

## Risks and Recommended Changes
1. **Overclock block is not idempotent** - `overclock.sh` only appends the prepared block to the end of `config.txt` and exits early on the next run, so manual edits or firmware changes will duplicate the block. Remove any existing section bounded by comments before writing, then insert current values.【F:install_modules/overclock.sh†L33-L50】
2. **Destructive copy fallback** - If `rsync` is unavailable, `sync_tree` deletes the destination with `rm -rf "$dest"` and only then copies content. This can destroy manual changes outside the repo. Safer options include iterative copy or a temporary staging directory.【F:install_modules/deploy_scripts.sh†L13-L34】
3. **@openai/codex install is hard-required** - `install_apps.sh` installs the package via `npm install -g @openai/codex`, but if it fails (for example, the package is deprecated) the script exits because of `set -e`. Treat failures as warnings so the install can continue.【F:install_modules/install_apps.sh†L29-L43】
4. **Risky Docker fallback** - If `docker.io` still lacks a binary after installation, the script downloads and runs a remote installer `curl -fsSL https://get.docker.com | sh`. This is a security risk and does not work offline. Prefer repository packages, or at least download the script to a file and verify checksums before execution.【F:install_modules/home_automation_stack.sh†L11-L35】
5. **Docker stack config is not regenerated** - After overwriting files (Mosquitto, Zigbee2MQTT, Home Assistant), the script only runs `docker compose up -d`. Running containers may continue using old configuration. Add `docker compose down` / `up -d --force-recreate` or restart individual services, or at least warn the user about required restarts.【F:install_modules/home_automation_stack.sh†L55-L101】
6. **`deploy_scripts.sh` uses global variables** - Variables `local_src` and `dest` are not declared as `local`, so expanding the script may override them. Consider adding `local` inside the loop to keep the logic safe in future edits.【F:install_modules/deploy_scripts.sh†L24-L33】

## Installer Readiness
- For a first clean install the workflow is functional: it detects the model, runs updates, installs tools, and deploys scripts and the Docker stack if requested.【F:install_rpi5_home.sh†L11-L40】
- For repeat runs, idempotency and safer fallbacks are needed, otherwise edits can be lost (`rm -rf`) or containers may not accept new configuration.
- Consider adding logging for step results (for example, verify that `/boot/firmware/config.txt` contains exactly one overclock block and that the docker compose restart completed successfully).

## Additional Notes
- The README correctly describes how to fetch and run the installer, including the list of deployed directories, which helps onboard new users.【F:README.md†L1-L35】
- Most supporting scripts (for example, `Backup/rpi_backup_pishrink.sh`) have commented configuration and interactive choices, so they are easy to adapt to specific environments.【F:Backup/rpi_backup_pishrink.sh†L1-L100】
- Before production deployment, review each directory (Fan, CPU_freq, home-automation-backup) and confirm that the target services and cron jobs match the expected configuration for the specific installation.
