# RPi5 Home Installer Review

## Overall assessment

The `install_rpi5_home.sh` entrypoint is generally well structured. It imports common helper functions from `install_modules/lib.sh`, enforces root execution, and presents the user with clear prompts before performing each major step. The workflow is modularised into small scripts, which keeps the responsibilities of each action separate and easy to follow.

## Positive findings

- `set -Eeuo pipefail` is consistently applied, which mitigates several classes of shell scripting errors.
- Root privileges are enforced up front via `require_root`, so later commands that need elevated rights will not fail unexpectedly.
- User prompts use helper utilities defined in `lib.sh`, providing a uniform user interaction surface and sensible defaults.
- Deployment of support scripts is handled through `deploy_scripts.sh`, which reuses rsync when available and falls back to POSIX tools otherwise.
- Installation steps cover the expected tooling for development and monitoring, and PiShrink is installed with an idempotent clone/update workflow.

## Potential issues and recommendations

1. **Idempotency of the overclock step**  
   The overclock module appends a configuration block to `/boot/firmware/config.txt` when it does not already contain the sentinel comment. If the user manually edits that section or upgrades the boot partition, the script will append a new block instead of updating the old one. Consider replacing the block using `crudini`, `crudini`, or `awk`/`perl` to ensure idempotent updates.

2. **`deploy_scripts.sh` variable scoping**  
   In `deploy_scripts.sh`, loop-local variables such as `local_src` and `dest` are not declared with the `local` keyword. Because `set -u` is active, an unexpected unset or reuse in another function could lead to confusing behaviour. Declaring them with `local` will keep the scope contained.

3. **Fallback behaviour when `rsync` is missing**  
   The fallback path for `sync_tree` removes the destination directory entirely before copying. On a misconfigured run, this may delete unrelated files that the user added manually. You could prompt for confirmation or use a safer copy strategy (e.g. `cp -a` with pruning of removed files afterwards).

4. **Docker stack prerequisites**  
   The Docker installation helper runs `curl https://get.docker.com | sh` when the `docker` CLI is not available. This requires outbound internet access and executes remote code. To reduce risk, consider shipping the official convenience script with a checksum, or instruct the user to install Docker manually.

5. **`@openai/codex` npm package**  
   The npm package `@openai/codex` is deprecated and may fail to install. It is optional, but the script does not handle installation failures gracefully (e.g. with `set -e`, the whole script will abort). Wrap the installation in `if ! npm install …; then warn …; fi` to make this optional dependency non-fatal.

6. **Service restarts after configuration changes**  
   When the MQTT password file or Zigbee2MQTT configuration is regenerated, running containers may continue using cached data. Consider stopping any running stack before overwriting configuration files to avoid inconsistent state.

## Conclusion

Aside from the cautions above, the installer is largely sound and should work as intended on a clean Raspberry Pi OS installation. Addressing the listed improvements would make it more robust for repeated runs and less surprising for end users.

