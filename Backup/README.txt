Instructions for this script

Grant execute permission:
    sudo chmod +x /home/vojrik/Scripts/Backup/rpi_backup_pishrink.sh

Create a symlink to run it from anywhere:
    sudo ln -s /home/vojrik/Scripts/Backup/rpi_backup_pishrink.sh /usr/local/bin/rpi_backup_pishrink

Run the backup:
    sudo rpi_backup_pishrink

Acknowledgements:
- rpi_backup_pishrink wraps the excellent [PiShrink](https://github.com/Drewsif/PiShrink) utility by Drew Bonasera. See `PiShrink_LICENSE` in this directory for the original MIT licence.
