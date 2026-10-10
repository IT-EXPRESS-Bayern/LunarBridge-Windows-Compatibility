# Gezielte EXE-Vorbereitung und Ausführung

`inspect` und `plan` funktionieren mit Python 3.10+ unter Windows und macOS. `doctor` und `launch` verlangen ausdrücklich natives Intel-macOS. Eine spätere Tahoe-Installation muss erst tatsächlich starten, bevor ein App-Test etwas über den Zielrechner aussagt.

## Einzelne Eingabe prüfen

```text
python tools/windows_compatibility.py inspect "Setup.exe"
python tools/windows_compatibility.py plan --mode install "Setup.exe" -- /quiet
```

Hier wird ausschließlich die gewählte Datei gelesen. Die Tools suchen nicht selbst nach Anwendungen und starten keinen eingebetteten Installer. Ein `/quiet`-Argument ist ein bewusst gewähltes Beispiel; es passt nur, wenn der konkrete Installer es unterstützt. Ohne solche App-Argumente bleibt die normale Installer-Oberfläche erhalten.

Der Inspector begrenzt Eingaben auf 512 MiB, Header auf 4096 Bytes, Abschnitte auf 96 und jede Importtabelle auf 512 Einträge. DLL-Namen sind begrenzt und enthalten keine Pfade. SHA-256 wird in 64-KiB-Blöcken berechnet. Virtuelle Nullfüllung wird nicht als Dateiinhalt interpretiert. Ungewöhnliche oder größere Dateien werden abgelehnt; das ist eine Inspector-Grenze und kein Beweis, dass die betreffende App unter Wine unbrauchbar wäre.

## Eine passende Laufzeit auswählen

Wine kommt separat vom Anwender beziehungsweise aus einer vorher geprüften Distribution. Für diesen freien Ausgangspfad ist Wine 11.0 oder neuer vorgesehen; das vollständige Paket muss den macOS- und bei x86 auch den WoW64-Unterbau enthalten. Eine einzelne kopierte Loader-Datei reicht üblicherweise nicht aus. Die öffentlich dokumentierte Quelle ist [WineHQ](https://www.winehq.org/); die [festgelegten Quellreferenzen](COMPATIBILITY.md) erklären die geprüfte Basis. Dieses Modul installiert keine Paketmanager oder Laufzeiten und verlangt keine Änderung von Gatekeeper, SIP oder Secure Boot.

Im folgenden Beispiel steht `/Pfad/zur/wine` für den konkreten **Mach-O-Executable-Loader** des gewählten Pakets. Shell-Wrapper und ein `.app`-Verzeichnis werden nicht automatisch aufgelöst. Die Headerprüfung ist eine Architekturbeobachtung und keine Codesignatur- oder Herkunftsprüfung.

```bash
python3 tools/windows_compatibility.py doctor --wine "/Pfad/zur/wine"
```

`doctor` ruft ausschließlich diese Datei mit `--version` auf, mit fünf Sekunden Zeitgrenze. Die Versionsausgabe wird auf das Wine-Versionsformat geprüft; fremde Ausgabe wird nicht in den JSON-Bericht übernommen. Der Aufruf prüft keinen 32-Bit-Test, keine Grafikfunktion und keine App.

## Eigener Prefix und Vorschau

```bash
python3 tools/windows_compatibility.py plan \
  --wine "/Pfad/zur/wine" \
  --prefix "$HOME/Library/Application Support/LunarBridge/Prefixes/Programm" \
  --mode install \
  "/Pfad/Setup.exe"
```

Der Plan legt keinen Prefix an und führt auch keine Versionsabfrage aus. Er zeigt Blocker und Abhängigkeitshinweise. Ein noch fehlender oder leerer Zielordner kann später verwendet werden. Ein nicht leerer bestehender Prefix wird nur angenommen, wenn er den eigenen gültigen Modulmarker trägt. Das Home-Verzeichnis und eine Dateisystemwurzel sind als Prefix ausgeschlossen.

## Ausdrücklich installieren oder starten

```bash
python3 tools/windows_compatibility.py launch \
  --wine "/Pfad/zur/wine" \
  --prefix "$HOME/Library/Application Support/LunarBridge/Prefixes/Programm" \
  --mode install \
  "/Pfad/Setup.exe"
```

Vor dem Start werden Eingabe und Runtime erneut gelesen und mit ihren Plan-Hashes verglichen; danach folgt die Versionsabfrage. Anschließend werden EXE und Wine-Datei nochmals frisch geprüft und ihre Hashes mit dem Plan verglichen. Ändert die Versionsprobe eine der Dateien, endet der Ablauf vor der Prefix-Erstellung und vor einem App-Aufruf. Bei einem x86-Image fordert der freie Ausgangspfad Wine 11+. Erst nach diesen Prüfungen wird ein fehlender dedizierter Prefix mit Modulmarker angelegt. Wine selbst initialisiert seine Windows-Umgebung und der ausgewählte EXE-Installer entscheidet über seine Installation.

Eine anschließend installierte EXE kann ausdrücklich im selben Prefix gestartet werden:

```bash
python3 tools/windows_compatibility.py launch \
  --wine "/Pfad/zur/wine" \
  --prefix "$HOME/Library/Application Support/LunarBridge/Prefixes/Programm" \
  --mode run \
  "/Pfad/zum/Prefix/drive_c/Program Files/Programm/Programm.exe" \
  -- "Dokument mit Leerzeichen.txt"
```

Beide Modi rufen `wine` mit der gewählten EXE und einer echten Argumentliste auf. Es gibt kein `cmd /c`, keine Shell und keine erfundene stille Installationsoption. `install` benennt den gewählten Zweck; es bietet keinen automatischen Erfolgsnachweis. Auch Exitcode 0 lässt `installation_verified` und `app_compatibility` unbestätigt.

Die Umgebung übernimmt eine kleine Auswahl normaler Mac-Umgebungsvariablen und setzt ausschließlich den eigenen `WINEPREFIX` sowie `WINEDEBUG=-all`. Bestehende Wine-DLL-Overrides, `WINEARCH` und LD-/DYLD-Injektionsvariablen werden nicht übernommen. Die Anwendung ist weiterhin ein normaler Benutzerprozess mit dessen Zugriffsrechten. Der Prefix isoliert Installationsdateien und Konfigurationen, nicht alle Datei- oder Netzwerkzugriffe.

## Rückgabewerte und Berichte

| Tool-Rückgabe | Bedeutung |
| --- | --- |
| 0 | Prüfung/Plan/Versionsabfrage erfolgreich oder Wine-Prozess mit Exitcode 0 beendet |
| 2 | begründeter Prüf-, Runtime- oder Startfehler |
| 4 | gestarteter Wine-Prozess mit einem anderen Exitcode beendet |

JSON enthält Hashes, numerische Metadaten, erlaubte DLL-Namen, Blocker und die Anzahl der Argumente. Absolute Pfade und App-Argumente fehlen absichtlich. Wine-/App-Ausgaben gehen an die lokale Sitzung und werden nicht als öffentliche Diagnose gespeichert. `executed` beschreibt einen erfolgten Tool-/Wine-Aufruf; es ist kein Nachweis einer korrekten Installation oder App-Funktion. Fehlerberichte benennen `app_executed: false`, wenn kein App-Prozess erfolgreich gestartet wurde.

Die Hashprüfung ist keine Authentifizierung und keine atomare Übergabe an Wine. Dateien oder Prefix-Inhalte dürfen zwischen Prüfung und Start nicht von anderen Prozessen verändert werden. Das Modul löscht weder Prefixes noch Installationsdateien automatisch.

