DISK CHECKS – Dokumentace a plán
================================

RYCHLÝ PŘEHLED (KDY CO BĚŽÍ + LOG)
----------------------------------
- Denně 19:00: SMART rychlá kontrola + RAID watch
  - Cron: `0 19 * * *`
  - Logy: `/var/log/Disck_checks/smart_daily.log`, `/var/log/Disck_checks/raid_watch.log`

- Týdně (úterý) 17:50: krátké SMART self‑testy
  - Cron: `50 17 * * 2`
  - Log: `/var/log/Disck_checks/smart_daily.log`

- Měsíčně (první úterý) 08:00: RAID parity check (check)
  - Cron: `0 8 * * 2 [ $(date +%d) -le 7 ] && …`
  - Log: `/var/log/Disck_checks/raid_check.log`

- Měsíčně (první úterý) 18:30: dlouhé SMART self‑testy
  - Cron: `30 18 * * 2 [ $(date +%d) -le 7 ] && …`
  - Log: `/var/log/Disck_checks/smart_daily.log`

Pozn.: Na ploše jsou zástupci k aktivním logům se stejnými názvy souborů.

AKTUÁLNÍ TEST PLÁN (CRON)
-------------------------
- Denní kontroly (každý den v 19:00)
  - Sekvenčně: SMART rychlá kontrola (bez self‑testů) → RAID watch
  - Cron (root):
    0 19 * * * nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/smart_daily.sh >/tmp/smart_daily.cron.log 2>&1; nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/raid_watch.sh >/tmp/raid_watch.cron.log 2>&1

- Týdenní krátké SMART self‑testy (úterý v 17:50)
  - Cron (root):
    50 17 * * 2 nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/smart_daily.sh --short >/tmp/smart_short.cron.log 2>&1
  - Pozn.: Pokud je první úterý v měsíci, skript krátké testy automaticky přeskočí (kvůli dlouhým testům téhož dne).

- Měsíční dlouhé SMART self‑testy (první úterý v 18:30)
  - Cron (root):
    30 18 * * 2 [ $(date +\%d) -le 7 ] && nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/smart_daily.sh --long >/tmp/smart_long.cron.log 2>&1

- RAID parity check (první úterý v 08:00 – během dne kvůli hluku)
  - Cron (root):
    0 8 * * 2 [ $(date +\%d) -le 7 ] && nice -n 10 ionice -c3 /home/vojrik/Scripts/Disck_checks/raid_check.sh >/tmp/raid_check.cron.log 2>&1

Všechny časy používají časové pásmo systému (systemd/cron).

Pozn.: V cronu se pole den‑v‑měsíci a den‑v‑týdnu vyhodnocují jako logické „NEBO“. Výraz typu `1-7 * 2` by tedy spouštěl job v kterémkoli dni 1.–7. A ZÁROVEŇ každé úterý. Proto je použita podmínka `[ $(date +\%d) -le 7 ]` a samotné pole „den v týdnu“.


PŘEHLED SKRIPTŮ
---------------
1) smart_daily.sh
   - Účel: Denní rychlá kontrola disků přes SMART + možnost spouštět self‑testy.
   - Co dělá:
     - Identifikuje systémový disk (root) a VYNECHÁ jej z testování.
     - Pro ostatní disky (NVMe i SATA/USB) načte SMART health, atributy a error logy.
     - Vyhodnotí stav podle klíčových ukazatelů (viz Kritéria níže).
     - Shromáždí “životní čítače” (NVMe: Power Cycles; SATA: Power/Load/Start_Stop counts) do přehledu.
     - Při nálezu problémů odešle e‑mail a vše zaloguje.
     - Pokud zrovna běží self‑test (krátký/dlouhý), přidá krátký status „Self‑test status: … in progress …“ do logu i v denní rychlé kontrole.
     - Detekuje dlouho běžící self‑testy (podezření na „zaseknutí“) a upozorní v souhrnu:
       - Krátký test: považuje se za zaseknutý po > 2 h.
       - Dlouhý/extended: považuje se za zaseknutý po > 24 h.
       - Upozornění se započítá mezi problémy a vyvolá e‑mail.
       - Stav se sleduje napříč běhy pomocí stavových souborů v `/var/lib/Disck_checks` (resp. `~/.local/state/Disck_checks`).
   - Self‑testy:
     - `--short` spustí krátké self‑testy na všech nesystémových discích.
     - `--long` spustí dlouhé/extended self‑testy na všech nesystémových discích.
     - Self‑testy se spouští neblokujícím způsobem (běží na pozadí), skript pouze čte aktuální stav.
     - Pokud je první úterý v měsíci a skript běží s `--short`, krátké testy se přeskočí (kvůli plánovaným dlouhým testům večer).
   - Další volby:
     - `--dry-run` pouze simuluje kroky (nevzbudí disky, nespouští smartctl) a vypíše, co by běželo.
     - `--wait` při `--short`/`--long` čeká na dokončení self‑testů (hodí se pro manuální běh; může trvat desítky minut až hodiny).
     - `--abort-running` ukončí právě běžící self‑testy na všech nesystémových discích (přes `smartctl -X`).
   - Log: `/var/log/Disck_checks/smart_daily.log` (+ zástupce na ploše)
   - E‑mail: při problému na `Vojta.Hamacek@seznam.cz` (přes msmtp, viz níže)

2) raid_watch.sh
   - Účel: Denní kontrola stavu mdraid polí (degradace, selhání členů apod.).
   - Co dělá:
     - Najde všechna md pole z `/proc/mdstat`.
     - Pro každé pole získá detail přes `mdadm --detail /dev/mdX`.
     - Z `sysfs` přečte stav členů: `/sys/block/mdX/md/dev-*/state`.
     - Vyhodnotí, zda je pole v pořádku (viz Kritéria níže).
     - Při problému odešle e‑mail a vše zaloguje.
   - Log: `/var/log/Disck_checks/raid_watch.log` (+ zástupce na ploše)
   - Pozn.: Pro běh je vhodné root prostředí (v cronu běží jako root).

3) raid_check.sh
   - Účel: Měsíční paritní kontrola mdraid polí („check“).
   - Co dělá:
     - Na každém md poli (kde je to možné) zapíše do `/sys/block/mdX/md/sync_action` hodnotu `check`.
     - Průběžně čeká, dokud se všechna pole nevrátí do stavu `idle` (kontrola dokončena).
     - Načte `mismatch_cnt` a vyhodnotí případné neshody parity.
     - Doporučí případnou opravu: `echo repair > /sys/block/mdX/md/sync_action` (provádějte vědomě).
     - Na SIGINT/SIGTERM skript nastaví `idle` (bezpečné ukončení kontroly) a skončí.
   - Volby: `--dry-run` pouze simuluje akce bez zápisu do `/sys`.
   - Log: `/var/log/Disck_checks/raid_check.log` (+ zástupce na ploše)

4) daily_checks.sh (nepovinný helper)
   - Jednoduchý wrapper, který sekvenčně spouští `smart_daily.sh` a `raid_watch.sh` a loguje do `daily_checks.log`.
   - Aktuálně NENÍ volaný z cronu (nahrazeno jedním řádkem se dvěma příkazy), lze použít ručně.


KRITÉRIA SELHÁNÍ A ODESLÁNÍ E‑MAILU
-----------------------------------
SMART (smart_daily.sh)
- NVMe disky:
  - Návratový kód smartctl s bitem „health“ (rc&2 != 0) → selhání.
  - „Media and Data Integrity Errors“: nenulová hodnota → selhání.
  - „Percentage Used“: ≥ 80 % → selhání (upozornění na opotřebení).

- SATA/USB disky:
  - Návratový kód smartctl s bitem „health“ (rc&2 != 0) → selhání.
  - Reallocated_Sector_Ct: > 0 → selhání.
  - Current_Pending_Sector: > 0 → selhání.
  - Offline_Uncorrectable: > 0 → selhání.

Poznámky:
- „Selhání“ zde znamená, že se do souhrnu zapíše problém a po skončení běhu se odešle e‑mail.
- „Životní čítače“ (Power/Load/Start_Stop) se vždy logují pro přehled, ale samy o sobě e‑mail nespouští.
- Systemový disk (s root FS) je z vyhodnocení vynechán.

RAID watch (raid_watch.sh)
- E‑mail se odešle, pokud platí alespoň jedna z podmínek:
  - Stav pole obsahuje „degraded“.
  - Failed Devices > 0.
  - Active Devices < Raid Devices (pole není plně aktivní).
  - Některý člen má stav odlišný od „in_sync“ (podle `/sys/block/mdX/md/dev-*/state`).

RAID parity check (raid_check.sh)
- Po dokončení „check“:
  - Pokud je `mismatch_cnt` nenulový, jedná se o problém → odešle se e‑mail s doporučením „repair“.
  - Pokud `mismatch_cnt` == 0, e‑mail se neposílá.


LOGY A ZÁSTUPCI
----------------
- Primární umístění logů: `/var/log/Disck_checks` (při běhu z cronu/root).
- Fallback (ruční běh bez sudo): `~/Disck_checks/logs`.
- Na ploše jsou zástupci (symlinky), které VŽDY ukazují na aktuální umístění logu:
  - `smart_daily.log` → aktivní log (system nebo fallback)
  - `raid_watch.log`  → aktivní log (system nebo fallback)
  - `raid_check.log`  → aktivní log (system nebo fallback)
- Při běhu jako root skripty nastaví vlastníka logu na `vojrik:vojrik`, aby bylo možné číst bez sudo.


MDADM CRON – PREVENCE DUPLICIT
-------------------------------
- V `/etc/cron.d/mdadm` byly vlastní položky pro `raid_check.sh` (měsíčně) a `raid_watch.sh` (denně),
  které kolidovaly s novým plánem. Tyto řádky jsou nyní zakomentovány s komentářem
  „DISABLED (replaced by root crontab)“ a nahrazeny definicemi v root crontabu (viz plán výše).


E‑MAIL OZNÁMENÍ
---------------
- Odesílá se přes `msmtp` s konfigurací: `/home/vojrik/Scripts/Disck_checks/.msmtprc`.
- Příjemce: `Vojta.Hamacek@seznam.cz`.
- Předmět:
  - SMART: `[SMART ALERT] <hostname> – problémy detekovány`
  - RAID:  `[RAID ALERT]  <hostname> – problém detekován` (watch) / `– neshody parity` (check)
- Tělo obsahuje shrnutí problémů a plný log běhu pro rychlou diagnostiku.


RUČNÍ SPUŠTĚNÍ A TESTOVÁNÍ
---------------------------
- Denní rychlá SMART kontrola (bez self‑testů):
  sudo /home/vojrik/Scripts/Disck_checks/smart_daily.sh

- Krátké SMART self‑testy (spustí testy na pozadí):
  sudo /home/vojrik/Scripts/Disck_checks/smart_daily.sh --short

- Dlouhé SMART self‑testy (spustí testy na pozadí):
  sudo /home/vojrik/Scripts/Disck_checks/smart_daily.sh --long

- Suchý běh (bez zásahu do disků):
  sudo /home/vojrik/Scripts/Disck_checks/smart_daily.sh --dry-run [--short|--long]
  sudo /home/vojrik/Scripts/Disck_checks/raid_check.sh --dry-run

- RAID parity check (pozor: IO‑náročné):
  sudo /home/vojrik/Scripts/Disck_checks/raid_check.sh &
  # Stav:  cat /proc/mdstat | grep -i check
  # Bezpečné ukončení: pošli SIGINT (skript přepne pole do idle):
  sudo pkill -INT -f /home/vojrik/Scripts/Disck_checks/raid_check.sh


PŘEDPOKLADY A POZNÁMKY
----------------------
- Nutné balíčky: `smartmontools` (smartctl), `mdadm`, `hdparm`, `msmtp`.
- Cron běží pod rootem (přístup k /sys a smartctl bez interaktivního sudo).
- Skripty používají `nice` a `ionice` (nižší priorita CPU/IO) v cronu.
- Z vyhledávání disků jsou vyloučeny `loop` a `zram` zařízení.
- Self‑testy SMART běží v zařízení na pozadí; jejich výsledky se projeví v dalších výpisech smartctl.
