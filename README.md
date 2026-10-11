# LunarBridge Windows Compatibility

Dieses eigenständige Modul bereitet ausdrücklich ausgewählte Windows-Programme für einen Wine-Start unter nativem Intel-macOS vor. Es liest EXE-Metadaten, zeigt Architektur und mögliche Laufzeitabhängigkeiten und verwendet einen eigenen Prefix für Installation und Betrieb.

**Aktueller Stand:** PE-Prüfung, Startablauf und Wine-Quellbuild sind implementiert. Die portable CI besteht **79 Tests je Windows-/Intel-macOS-Host**. Der getrennte [Runtime-Lauf 38110355646](https://github.com/IT-EXPRESS-Bayern/LunarBridge-Windows-Compatibility/actions/runs/38110355646) hat Wine 11.0 auf Intel-macOS 26.6.1 gebaut und beide eigenen **x64-/x86-Windows-Konsolenprogramme über unseren Launcher ausgeführt**: jeweils Code 0 sowie geprüfte stdout- und Dateitoken; x86 im neuen WoW64-Modus. Bericht, exakter Quellstand und Grenzen stehen in [RUNTIME_VALIDATION.json](docs/RUNTIME_VALIDATION.json). Unter Windows wurden die Dateien ausschließlich gebaut beziehungsweise gelesen. Ein Wine-Start auf dem Samsung Galaxy Book5 Pro16 und die Funktion einer Nutzeranwendung sind weiterhin offen. Die separate LunarBridge-Grafikentwicklung hat bislang keine bestätigte macOS-GPU-Beschleunigung.

## Funktionen

- PE32/PE32+, x86/x64/ARM, Subsystem, DLL-/Systemkennzeichen und begrenzte Headerprüfung.
- Normale und verzögerte DLL-Importe; Hinweise auf Visual C++, CLR/.NET und Grafik-APIs.
- SHA-256 für die gewählten Eingaben; erneute Prüfung vor und nach der Wine-Versionsabfrage, bevor ein Prefix beschrieben oder eine App gestartet wird.
- Prüfung der ausdrücklich ausgewählten Wine-Datei auf einen Intel-Mach-O-Executable-Header.
- Eigener Prefix mit Herkunftsmarker; keine automatische Übernahme eines bestehenden fremden Prefix.
- `inspect` und `plan` lesen ausschließlich. `doctor` prüft auf Intel-macOS die ausgewählte Wine-Datei mit `--version`. `launch` startet ausdrücklich diese Laufzeit mit einer Argumentliste ohne Shell.
- JSON-Berichte enthalten weder absolute Eingabepfade noch App-Argumente. Wine-/App-Ausgaben werden nicht in Berichte aufgenommen.
- Separater, ausdrücklich gestarteter Wine-11-Quellbuild auf Intel-macOS-CI: feste Quellen-/Compilerhashes, eigene x64-/x86-Konsole, Ergebnisprüfung, erhaltene Fremdlizenzen und vollständiges Wine-Quellarchiv.

## Benutzung

Voraussetzung für die Tools ist Python 3.10 oder neuer. Für eine echte Ausführung kommen natives Intel-macOS und eine selbst ausgewählte, separat bereitgestellte Wine-Laufzeit hinzu. Dieses Repository enthält keine Wine-, Windows- oder Microsoft-Laufzeitdateien.

Eine ausgewählte Datei bereits unter Windows prüfen:

```text
python tools/windows_compatibility.py inspect "Programm.exe"
python tools/windows_compatibility.py plan --mode install "Setup.exe" -- /quiet
```

Der Plan weist unter Windows `requires_native_intel_macos` aus. Die macOS-Vorbereitung und der konkrete Start sind in [USAGE.md](docs/USAGE.md) beschrieben. Der aktuelle freie Ausgangspunkt ist Wine 11.0 oder neuer mit einem 64-Bit-Prefix und passender WoW64-Unterstützung für x86-Programme. Eine Versionsnummer allein bestätigt keine App-Kompatibilität.

## Grenzen

Importe sind Hinweise: dynamisch geladene DLLs, eingebettete Installer, nachgeladene Komponenten, Dienste, DRM und Anti-Cheat werden damit nicht vollständig erkannt. Der Inspector verifiziert keine Authenticode-Signatur und beurteilt nicht, ob eine Datei vertrauenswürdig ist. Ein Prefix ist ein Ablage- und Konfigurationsbereich; er ist keine Sicherheits-Sandbox.

Windows-Kernel-Treiber und ARM-Programme gehören nicht zum vorgesehenen Startpfad. Samsung-Hardwarefunktionen brauchen weiterhin eigene native Treiber beziehungsweise APIs. Die Installation einer passenden Windows-App ersetzt diese Arbeit nicht. Große oder ungewöhnliche PE-Varianten können an den dokumentierten Grenzen des konservativen Inspectors scheitern.

## Prüfung und Quellen

```text
python -m unittest discover -s tests -v
python tools/run_tests.py
```

Die portable CI prüft dieselben synthetischen Fixtures auf Windows und Intel-macOS. Sie installiert Wine nicht und führt keine Windows-Datei aus. [VALIDATION.md](docs/VALIDATION.md) unterscheidet diese Tests vom echten Runtime-Lauf auf dem CI-Mac und vom noch offenen Samsung-Gerätetest; [COMPATIBILITY.md](docs/COMPATIBILITY.md) enthält die Primärquellen und den Grafikpfad.

Der zusätzliche Workflow `Real Wine 11 runtime on Intel macOS` baut einen begrenzten Diagnosebuild und führt ausschließlich die eigenen Programme aus. Der erfolgreiche Lauf belegt Konsolenausgabe, Dateischreibzugriff und neuen WoW64-Loader im 64-Bit-Prefix. Quellen, Abhängigkeiten, gemessene Buildzeit, Artefaktdigest und Grenzen stehen in [RUNTIME_BUILD.md](docs/RUNTIME_BUILD.md). Grafik-, Medien-, TLS-, .NET- und beliebige Nutzeranwendungen bleiben ungeprüft; das Runtime-Paket ist für den CI-Prefix konfiguriert und seine Verlagerung ungetestet.

Eigener Code: **GPL-3.0-only**, kommerzielle Nutzung erlaubt. Externe Laufzeiten und Anwendungen behalten ihre eigenen Lizenzen. Siehe [NOTICE](NOTICE) und [LICENSE](LICENSE).

Projektfamilie: [LunarBridge Hackintosh](https://github.com/IT-EXPRESS-Bayern/LunarBridge-Hackintosh). Dieses Modul ist Userland-Software und enthält keinen Hardware-Kext.

Der erfolgreiche Online-Prüflauf und sein exakter Quellstand sind in [docs/CI_VALIDATION.json](docs/CI_VALIDATION.json) festgehalten. Spätere Dokumentations-Commits sind davon getrennt; dieser CI-Lauf ist kein Gerätefunktionstest auf dem Samsung.
