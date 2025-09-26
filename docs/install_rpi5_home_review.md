# Hodnocení hlavního repozitáře RPi5 Home

## Shrnutí stavu
- Modulární instalátor `install_rpi5_home.sh` je přehledný a používá společné helpery z `install_modules/lib.sh`, takže základní tok instalace je konzistentní.
- V repozitáři jsou připravené samostatné adresáře se skripty (Backup, CPU_freq, Fan, home-automation-backup atd.), které se nasazují přes `deploy_scripts.sh` a pokrývají hlavní funkce domácí automatizace.
- Několik kroků instalace však není idempotentních (overclock blok, docker stack) a část fallback logiky je destruktivní (`rm -rf`), takže opakované spuštění skriptu může vést k nekonzistentnímu stavu.

## Pozitivní zjištění
- Všechny modulární skripty v `install_modules/` používají `set -Eeuo pipefail` a sdílené logovací funkce, čímž se minimalizuje riziko tichého selhání.【F:install_rpi5_home.sh†L1-L41】【F:install_modules/lib.sh†L1-L64】
- Základní instalace se skládá z jasných kroků (overclock, OS update, instalace balíčků, nasazení skriptů) a uživatel je může podle potřeby přeskočit nebo zopakovat.【F:install_rpi5_home.sh†L11-L40】
- Skript `Backup/rpi_backup_pishrink.sh` zastavuje kontejnery před vytvořením image a po dokončení je znovu spouští, takže zálohy jsou konzistentní.【F:Backup/rpi_backup_pishrink.sh†L106-L154】

## Rizika a doporučené úpravy
1. **Overclock blok není idempotentní** – `overclock.sh` pouze připojí předpřipravený blok na konec `config.txt` a při dalším běhu skončí hned na začátku, takže ruční úpravy nebo změny firmwaru povedou k duplikaci bloku. Doporučuji před zápisem odstranit existující sekci ohraničenou komentáři a následně vložit aktuální hodnoty.【F:install_modules/overclock.sh†L33-L50】
2. **Destruktivní fallback kopírování** – Pokud není k dispozici `rsync`, funkce `sync_tree` smaže cílový adresář `rm -rf "$dest"` a teprve potom kopíruje obsah. To může zničit ruční změny mimo repozitář. Bezpečnější je iterativní kopírování nebo použití dočasného adresáře.【F:install_modules/deploy_scripts.sh†L13-L34】
3. **Instalace @openai/codex je tvrdě vyžadovaná** – `install_apps.sh` instaluje balíček přes `npm install -g @openai/codex`, ale při selhání (např. balíček je ukončený) skript kvůli `set -e` spadne. Ošetřete chybu jako varování, aby instalace pokračovala.【F:install_modules/install_apps.sh†L29-L43】
4. **Nebezpečný fallback pro Docker** – Pokud po instalaci `docker.io` stále chybí binárka, skript stáhne a spustí vzdálený instalátor `curl -fsSL https://get.docker.com | sh`. To je bezpečnostní riziko a na offline systémech nefunguje. Preferujte balíčky z repozitářů nebo alespoň stahujte skript do souboru a ověřte checksum před spuštěním.【F:install_modules/home_automation_stack.sh†L11-L35】
5. **Konfigurace Docker stacku se nepřegeneruje** – Po přepsání souborů (Mosquitto, Zigbee2MQTT, Home Assistant) skript pouze spustí `docker compose up -d`. Běžící kontejnery tak mohou dál používat starou konfiguraci. Přidejte `docker compose down` / `up -d --force-recreate` nebo restart jednotlivých služeb, případně upozorněte uživatele na nutnost restartu.【F:install_modules/home_automation_stack.sh†L55-L101】
6. **`deploy_scripts.sh` používá globální proměnné** – Proměnné `local_src` a `dest` nejsou deklarované jako `local`, takže při rozšíření skriptu může dojít k jejich přepsání. Zvažte doplnění `local` pro proměnné uvnitř smyčky, aby logika zůstala bezpečná i při budoucích úpravách.【F:install_modules/deploy_scripts.sh†L24-L33】

## Připravenost instalátoru
- Pro první čistou instalaci je workflow funkční: detekuje model, provede update, nainstaluje nástroje a nasadí skripty i Docker stack, pokud si je uživatel vyžádá.【F:install_rpi5_home.sh†L11-L40】
- Na opakované běhy je ale potřeba doplnit idempotenci a bezpečnější fallbacky, jinak může dojít ke ztrátě úprav (`rm -rf`) nebo k tomu, že kontejnery nepřijmou nové konfigurace.
- Doporučuji také přidat logování výsledků jednotlivých kroků (např. kontrola, že `/boot/firmware/config.txt` obsahuje právě jeden overclock blok a že docker compose restart proběhl úspěšně).

## Další poznatky
- README správně popisuje postup stažení a spuštění instalátoru, včetně výčtu nasazovaných adresářů, což usnadňuje onboard novým uživatelům.【F:README.md†L1-L35】
- Většina podpůrných skriptů (např. `Backup/rpi_backup_pishrink.sh`) má komentovanou konfiguraci a nabízí interaktivní volby, takže se snadno přizpůsobují konkrétnímu prostředí.【F:Backup/rpi_backup_pishrink.sh†L1-L100】
- Před ostrým nasazením doporučuji projít jednotlivé adresáře (Fan, CPU_freq, home-automation-backup) a ověřit, že cílové služby a cron úlohy odpovídají očekávané konfiguraci konkrétní instalace.
