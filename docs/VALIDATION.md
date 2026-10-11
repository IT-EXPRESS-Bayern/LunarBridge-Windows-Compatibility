# Geprüfter Stand

Die Implementierung besteht unter Windows **79 portable Tests**, ohne Fehler oder ausgelassene Tests. Die vollständigen strukturierten Angaben und SHA-256 der geprüften Quellen stehen in [VALIDATION.json](VALIDATION.json). Die Unit-Testdateien entstehen als synthetische Fixtures in temporären Verzeichnissen; sie enthalten keinen ausführbaren Anwendungscode.

Geprüft wurden PE32/PE32+, x86/x64/ARM, normale und verzögerte Importe einschließlich älterer VA-Einträge, CLR-Hinweise, Zertifikat-Dateigrenzen, ungültige Signaturen, Abschnitte, virtuelle Nullfüllung, abgeschnittene Daten sowie 100 reproduzierbare Headermutationen. Mach-O-/Fat-/Fat64-Headerprüfung, Prefix-Herkunft, Argumentgrenzen, Umgebungsvariablen, ausbleibende Windows-Ausführung, wörtliche Shell-Metazeichen, nachträglich veränderte Eingaben und Runtime-Fehler haben eigene Tests.

Der Argumenttest verwendet absichtlich Pfade mit `..` und prüft die tatsächlich ausgewählten normalisierten EXE-, Wine- und Prefix-Pfade. Sämtliche App-Argumente müssen wörtlich unverändert bleiben. Zwei weitere Regressionstests lassen die simulierte Versionsprobe jeweils EXE beziehungsweise Wine-Datei verändern. Beide Änderungen müssen vor einer Prefix-Erstellung und vor einem App-Aufruf abgelehnt werden.

Die Wine-Prozessaufrufe werden in diesen Tests abgefangen. Ein simuliertes Wine-`--version` ist kein geladener Mac-Loader. Erfolgreiche Tests beweisen weder die Lauffähigkeit einer realen EXE noch eine vorhandene Wine-Installation, native Grafikausgabe oder die GPU-Beschleunigung des Samsung-Laptops.

Die CI führt dieselben synthetischen Tests auf `windows-latest` und `macos-26-intel` aus. Ihr Workflow ist fest auf einen Checkout-Commit gepinnt und besitzt ausschließlich Leserechte für Repository-Inhalte. Der vorherige erfolgreiche 49-Test-Quellstand ist in [CI_VALIDATION.json](CI_VALIDATION.json) belegt. Die neuen 79 Tests und der korrigierte echte Runtime-Workflow brauchen einen eigenen veröffentlichten Online-Lauf.

30 neue portable Tests prüfen das Buildmanifest, Hash-/Größenfehler, HTTPS-/Quellgrenzen, sichere Tar-Strukturen, Expansion und Linkpfade, feste Compilerargumente, Ausschluss von CRT/Grafikabhängigkeiten, Ergebnis-/Dateitoken, Rückgabecodes, Herkunft des Launcher-Berichts, Logbereinigung und stabile Paketmetadaten. Die zusätzliche Python-Grenzprüfung lehnt eine Version unter 3.12 vor Downloads, Verzeichnisanlage und Prozessstart ab. Die Tests starten weder Compiler noch Wine. Ein realer Windows-Aufruf von `--build-and-test` wurde zusätzlich geprüft: Er liefert `requires_native_intel_macos` und legt keinen Buildbereich an.

Der eigene C-Testprogrammcode wurde separat unter Windows mit der bereits vorhandenen Zig-0.15.2-Toolchain für x64 und x86 übersetzt. Die entstandenen privaten PE-Dateien sind jeweils 3.072 Bytes groß und deklarieren ausschließlich `kernel32.dll`, Console-Subsystem 3 und die erwartete Architektur. Zig braucht hier eigene Header-/Linkerargumente; diese Vorprüfung ersetzt den LLVM-MinGW-Compile-Schritt auf dem Mac nicht. Die Dateien wurden gelesen und **nicht ausgeführt**. Es liegt weiterhin kein lokaler Wine-/Windows-App-Laufnachweis vor.

Der neue Runtime-Workflow baut unmodifiziertes Wine 11.0 mit gepinnten Quellen und führt beide eigenen Programme über unseren Launcher auf einem echten Intel-macOS-26-Host aus. `BUILD_REPORT.json` muss die echten Ergebnischecks belegen. Quelle, Lizenzen, Abhängigkeiten und Grenzen sind in [RUNTIME_BUILD.md](RUNTIME_BUILD.md) beschrieben. Vor der tatsächlichen CI-Ausführung bleibt diese Laufzeitprüfung offen.

Für eine echte Qualifizierung bleiben der native Intel-macOS-Start, das gewählte vollständige Wine-Paket, eine ausdrücklich ausgewählte x64- und gegebenenfalls x86-App sowie deren beobachtete Funktion erforderlich. Grafikprogramme benötigen zusätzlich einen auf dem Zielgerät belegten Renderpfad. Windows-Hardwaretreiber werden durch dieses Modul nicht bereitgestellt.

