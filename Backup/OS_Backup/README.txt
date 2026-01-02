Instructions for this script

Grant execute permission:
    sudo chmod +x /home/vojrik/Scripts/Backup/OS_Backup/rpi_backup_pishrink.sh

Create a symlink to run it from anywhere:
    sudo ln -s /home/vojrik/Scripts/Backup/OS_Backup/rpi_backup_pishrink.sh /usr/local/bin/rpi_backup_pishrink

Run the backup:
    sudo rpi_backup_pishrink

Note: If you already had a symlink before moving files, recreate it using the command above.

Acknowledgements:
- rpi_backup_pishrink wraps the excellent [PiShrink](https://github.com/Drewsif/PiShrink) utility by Drew Bonasera. See `PiShrink_LICENSE` in this directory for the original MIT licence.
