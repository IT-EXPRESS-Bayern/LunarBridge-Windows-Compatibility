# Geprüfter Stand

Die Implementierung besteht unter Windows **49 Tests**, ohne Fehler oder ausgelassene Tests. Die vollständigen strukturierten Angaben und SHA-256 der geprüften Quellen stehen in [VALIDATION.json](VALIDATION.json). Testdateien entstehen ausschließlich als synthetische Fixtures in temporären Verzeichnissen; sie enthalten keinen ausführbaren Anwendungscode.

Geprüft wurden PE32/PE32+, x86/x64/ARM, normale und verzögerte Importe einschließlich älterer VA-Einträge, CLR-Hinweise, Zertifikat-Dateigrenzen, ungültige Signaturen, Abschnitte, virtuelle Nullfüllung, abgeschnittene Daten sowie 100 reproduzierbare Headermutationen. Mach-O-/Fat-/Fat64-Headerprüfung, Prefix-Herkunft, Argumentgrenzen, Umgebungsvariablen, ausbleibende Windows-Ausführung, wörtliche Shell-Metazeichen, nachträglich veränderte Eingaben und Runtime-Fehler haben eigene Tests.

Der Argumenttest verwendet absichtlich Pfade mit `..` und prüft die tatsächlich ausgewählten normalisierten EXE-, Wine- und Prefix-Pfade. Sämtliche App-Argumente müssen wörtlich unverändert bleiben. Zwei weitere Regressionstests lassen die simulierte Versionsprobe jeweils EXE beziehungsweise Wine-Datei verändern. Beide Änderungen müssen vor einer Prefix-Erstellung und vor einem App-Aufruf abgelehnt werden.

Die Wine-Prozessaufrufe werden in diesen Tests abgefangen. Ein simuliertes Wine-`--version` ist kein geladener Mac-Loader. Erfolgreiche Tests beweisen weder die Lauffähigkeit einer realen EXE noch eine vorhandene Wine-Installation, native Grafikausgabe oder die GPU-Beschleunigung des Samsung-Laptops.

Die CI führt dieselben synthetischen Tests auf `windows-latest` und `macos-26-intel` aus. Ihr Workflow ist fest auf einen Checkout-Commit gepinnt und besitzt ausschließlich Leserechte für Repository-Inhalte. **Für diese Korrektur ist beim lokalen Bericht noch kein erfolgreich ausgeführter Online-CI-Lauf bestätigt.**

Für eine echte Qualifizierung bleiben der native Intel-macOS-Start, das gewählte vollständige Wine-Paket, eine ausdrücklich ausgewählte x64- und gegebenenfalls x86-App sowie deren beobachtete Funktion erforderlich. Grafikprogramme benötigen zusätzlich einen auf dem Zielgerät belegten Renderpfad. Windows-Hardwaretreiber werden durch dieses Modul nicht bereitgestellt.

