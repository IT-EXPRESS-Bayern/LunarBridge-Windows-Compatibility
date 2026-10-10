# LunarBridge Windows Compatibility

Dieses eigenständige Modul bereitet ausdrücklich ausgewählte Windows-Programme für einen Wine-Start unter nativem Intel-macOS vor. Es liest EXE-Metadaten, zeigt Architektur und mögliche Laufzeitabhängigkeiten und verwendet einen eigenen Prefix für Installation und Betrieb.

**Aktueller Stand:** PE-Prüfung und Startablauf sind implementiert und mit 49 synthetischen Tests unter Windows geprüft. Ein echter Wine-Start auf dem Samsung Galaxy Book5 Pro16 und die Funktion einer Nutzeranwendung sind noch offen. Die separate LunarBridge-Grafikentwicklung hat bislang keine bestätigte macOS-GPU-Beschleunigung; Direct3D-Programme bleiben deshalb zusätzlich unqualifiziert.

## Funktionen

- PE32/PE32+, x86/x64/ARM, Subsystem, DLL-/Systemkennzeichen und begrenzte Headerprüfung.
- Normale und verzögerte DLL-Importe; Hinweise auf Visual C++, CLR/.NET und Grafik-APIs.
- SHA-256 für die gewählten Eingaben; erneute Prüfung vor und nach der Wine-Versionsabfrage, bevor ein Prefix beschrieben oder eine App gestartet wird.
- Prüfung der ausdrücklich ausgewählten Wine-Datei auf einen Intel-Mach-O-Executable-Header.
- Eigener Prefix mit Herkunftsmarker; keine automatische Übernahme eines bestehenden fremden Prefix.
- `inspect` und `plan` lesen ausschließlich. `doctor` prüft auf Intel-macOS die ausgewählte Wine-Datei mit `--version`. `launch` startet ausdrücklich diese Laufzeit mit einer Argumentliste ohne Shell.
- JSON-Berichte enthalten weder absolute Eingabepfade noch App-Argumente. Wine-/App-Ausgaben werden nicht in Berichte aufgenommen.

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

Die CI prüft dieselben synthetischen Fixtures auf Windows und Intel-macOS. Sie installiert Wine nicht und führt keine Windows-Datei aus. [VALIDATION.md](docs/VALIDATION.md) unterscheidet diese Tests vom noch offenen echten Gerätetest; [COMPATIBILITY.md](docs/COMPATIBILITY.md) enthält die Primärquellen und den Grafikpfad.

Eigener Code: **GPL-3.0-only**, kommerzielle Nutzung erlaubt. Externe Laufzeiten und Anwendungen behalten ihre eigenen Lizenzen. Siehe [NOTICE](NOTICE) und [LICENSE](LICENSE).

Projektfamilie: [LunarBridge Hackintosh](https://github.com/IT-EXPRESS-Bayern/LunarBridge-Hackintosh). Dieses Modul ist Userland-Software und enthält keinen Hardware-Kext.

