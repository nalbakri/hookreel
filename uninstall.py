#!/usr/bin/env python3
"""
uninstall.py -- HookReel uninstaller.

Run on the HOST to stop and remove HookReel completely.
Media files are never deleted unless you explicitly confirm.

Usage:
    python3 uninstall.py
"""

import os
import sys
import shutil
import subprocess

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ask_yes_no(prompt, default="n"):
    hint = "[Y/n]" if default.lower() == "y" else "[y/N]"
    while True:
        try:
            value = input("{} {}: ".format(prompt, hint)).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nUninstall cancelled.")
            sys.exit(0)
        if not value:
            value = default.lower()
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("  Please enter y or n.")


def banner(text):
    print("\n" + "=" * 50)
    print(text)
    print("=" * 50)


def run(cmd, check=False):
    """Run a shell command, print output, return returncode."""
    print("  Running: {}".format(cmd))
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print("  {}".format(result.stdout.strip()))
    if result.stderr.strip():
        print("  {}".format(result.stderr.strip()))
    return result.returncode


# ---------------------------------------------------------------------------
# Uninstall steps
# ---------------------------------------------------------------------------

def stop_containers(project_dir):
    """Stop and remove all HookReel containers."""
    print("\n--- Stopping containers ---")
    rc = run("docker compose -f {}/docker-compose.yml down".format(project_dir))
    if rc != 0:
        print("  docker compose down failed -- trying manual removal")
        for name in ["hookreel", "hookreel-clamav", "gluetun", "jellyfin"]:
            run("docker rm -f {}".format(name))
    print("  [OK] Containers stopped")


def remove_volumes():
    """Remove Docker volumes created by HookReel."""
    print("\n--- Removing Docker volumes ---")
    volumes = [
        "hookreel_clamav_data",
        "hookreel_jellyfin_config",
        "hookreel_jellyfin_cache",
    ]
    for vol in volumes:
        rc = run("docker volume rm {}".format(vol))
        if rc == 0:
            print("  [OK] Removed volume: {}".format(vol))
        else:
            print("  [skip] Volume not found: {}".format(vol))


def remove_appdata(project_dir):
    """Remove appdata folders: config, logs, data, quarantine."""
    print("\n--- Removing appdata folders ---")
    folders = ["config", "logs", "data", "quarantine"]
    for folder in folders:
        path = os.path.join(project_dir, folder)
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                print("  [OK] Removed: {}".format(path))
            except Exception as exc:
                print("  [error] Could not remove {}: {}".format(path, exc))
        else:
            print("  [skip] Not found: {}".format(path))


def remove_project(project_dir):
    """Remove the entire project folder."""
    print("\n--- Removing project folder ---")
    try:
        shutil.rmtree(project_dir)
        print("  [OK] Removed: {}".format(project_dir))
    except Exception as exc:
        print("  [error] Could not remove {}: {}".format(project_dir, exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    project_dir = os.path.dirname(os.path.abspath(__file__))

    banner("HookReel Uninstaller")
    print("This will remove HookReel from your system.")
    print("Project folder: {}".format(project_dir))
    print("")
    print("Your media files (Movies, TV, Downloads) will NOT be touched.")
    print("Only HookReel's own data will be removed.")

    if not ask_yes_no("\nAre you sure you want to uninstall HookReel?", default="n"):
        print("Uninstall cancelled.")
        sys.exit(0)

    # Step 1 -- Stop containers
    stop_containers(project_dir)

    # Step 2 -- Remove volumes
    if ask_yes_no("\nRemove Docker volumes (ClamAV definitions, Jellyfin config)?", default="y"):
        remove_volumes()

    # Step 3 -- Remove appdata
    print("\nThe following folders will be deleted:")
    print("  - config/  (contains your .env and settings)")
    print("  - logs/    (HookReel log files)")
    print("  - data/    (HookReel database)")
    print("  - quarantine/ (quarantined files)")
    if ask_yes_no("\nRemove these folders?", default="y"):
        remove_appdata(project_dir)

    # Step 4 -- Remove project folder
    print("")
    print("WARNING: This will delete the entire HookReel project folder:")
    print("  {}".format(project_dir))
    print("This includes setup.py, docker-compose.yml, and all app code.")
    if ask_yes_no("Remove the project folder completely?", default="n"):
        # Final confirmation for destructive action
        confirm = input("Type REMOVE to confirm: ").strip()
        if confirm == "REMOVE":
            remove_project(project_dir)
        else:
            print("Confirmation not received -- project folder kept.")

    banner("Uninstall complete")
    print("HookReel has been removed.")
    print("Your media files are untouched.")
    print("")
    print("To reinstall, run: python3 setup.py")


if __name__ == "__main__":
    main()
