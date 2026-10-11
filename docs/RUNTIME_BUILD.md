# Echter Wine-Lauf auf dem Intel-macOS-CI-Host

Der separate Workflow `Real Wine 11 runtime on Intel macOS` baut Wine 11.0 auf `macos-26-intel` und muss zwei eigene Windows-Konsolenprogramme ausführen: ein PE32+-x64-Programm und ein PE32-x86-Programm im neuen WoW64-Modus. Die [portable CI 38110355544](https://github.com/IT-EXPRESS-Bayern/LunarBridge-Windows-Compatibility/actions/runs/38110355544) ist mit **79 Tests je Windows-/Intel-macOS-Host** erfolgreich abgeschlossen, exakt am Quellstand `3dcc431371543d80b69de3f0deacf979bb3b1ccd`; siehe [CI_VALIDATION.json](CI_VALIDATION.json). Diese Tests verwenden synthetische Fixtures und abgefangene Prozessaufrufe.

Der tatsächliche Build und die eigenen PE-Starts sind im separaten [Runtime-Lauf 38110355646](https://github.com/IT-EXPRESS-Bayern/LunarBridge-Windows-Compatibility/actions/runs/38110355646), Job `114384440039`, am selben Quellstand **erfolgreich abgeschlossen**. Der gelesene `BUILD_REPORT.json`, die Logs und zusätzlich gelesene eigene PE-/Ergebnisdateien bestätigen beide Starts mit Code 0 sowie exakten stdout- und Dateitoken. Der Host meldete Intel-macOS 26.6.1, Python 3.12.10, Apple clang 21.0.0 und SDK 26.5. Die strukturierten Nachweise stehen in [RUNTIME_VALIDATION.json](RUNTIME_VALIDATION.json).

Der Host ist ein fremder Intel-Mac. Erfolgreiche Programme dort bestätigen weder den nativen Samsung-Start noch Arc-130V-Beschleunigung oder eine Nutzeranwendung. Der Testbuild enthält keine Direct3D-, Metal-, OpenGL- oder Vulkan-Qualifizierung.

## Feste Quellen und Abhängigkeiten

Die ausführbare Rezeptur liest [ci/runtime-pins.json](../ci/runtime-pins.json). Jeder Bezug verwendet HTTPS, eine erlaubte Primärquelle, eine feste erwartete Dateigröße und SHA-256. Wine wird zusätzlich gegen SHA-512 geprüft. Die Werte wurden aus Upstream-Metadaten beziehungsweise dem bezogenen GNU-Archiv abgeglichen; die CI berechnet die Hashes jedes Downloads erneut.

| Bestandteil | Festgelegter Stand | Primärquelle und Nachweis |
| --- | --- | --- |
| Wine | 11.0, Quellcommit `db11d0fe6a169c457e23d007e20404643d067aa8` | [offizielles Quellarchiv](https://dl.winehq.org/wine/source/11.0/wine-11.0.tar.xz), [offizielle SHA-512-Liste](https://dl.winehq.org/wine/source/11.0/sha512sums.asc), [zugehörige Configure-Quelle](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/configure.ac) |
| LLVM-MinGW | Release 20260908, LLVM 23.1.1, Rezeptcommit `030097eeee87fcfd0f3bfe536b21cbd6e5d3b324` | [Maintainer-Release](https://github.com/mstorsjo/llvm-mingw/releases/tag/20260908), [Release-Asset-Metadaten mit SHA-256](https://api.github.com/repos/mstorsjo/llvm-mingw/releases/tags/20260908), [gepinntes Buildrezept](https://github.com/mstorsjo/llvm-mingw/tree/030097eeee87fcfd0f3bfe536b21cbd6e5d3b324) |
| GNU Bison | 3.8.2, SHA-256 `9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2` | [GNU-Quellarchiv](https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz); unter Windows bezogen und nachgerechnet |
| Python | 3.12.10, explizit `x64` im Runtime-Workflow | [offizieller Actions-Python-Build](https://github.com/actions/python-versions/releases/tag/3.12.10-14343898437), Paket `python-3.12.10-darwin-x64.tar.gz` im [Actions-Manifest](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json), fest gepinnte `setup-python`-Action |
| Native Werkzeuge | Apple clang/SDK, make, flex ab 2.5.33 und m4 des CI-Images | Vor dem Build abgefragt, im Bericht festgehalten; kein Homebrew- oder Systeminstallationsschritt |

Wine verlangt Bison ab Version 3.0; ein älterer Systemparser reicht nicht. Deshalb wird Bison aus der festen GNU-Quelle nur in den eigenen Buildbereich installiert. LLVM-MinGW liefert die x64-/i686-PE-Compiler; Wine verwendet den nativen 64-Bit-Apple-Compiler für seinen Unix-Unterbau. `--enable-archs=i386,x86_64 --with-mingw=llvm-mingw` wählt die neuen kombinierten PE-Architekturen. Der [Wine-11-Releasehinweis](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/ANNOUNCE.md) erklärt den gemeinsamen Loader und `WINEARCH=wow64`.

Der erste [Runtime-CI-Lauf](https://github.com/IT-EXPRESS-Bayern/LunarBridge-Windows-Compatibility/actions/runs/38109910123) scheiterte bereits im Python-Setup: Für die ursprünglich angegebene Version 3.12.14 war kein macOS-x64-Paket verfügbar. Wine wurde dabei weder gebaut noch gestartet. Die korrigierte Vorgabe 3.12.10 besitzt ein tatsächlich hochgeladenes Darwin-x64-Releasepaket mit 45.403.701 Bytes; der Manifesteintrag beschränkt es auf keine einzelne macOS-Version. Der Builder fordert weiterhin mindestens Python 3.12. Die Windows-Testumgebung verwendet unabhängig davon ihre tatsächlich vorhandene Version, die im lokalen Prüfbericht steht.

Archive werden vor dem Entpacken geprüft: begrenzte Anzahl/Expansion, festes Wurzelverzeichnis, keine absoluten oder ausbrechenden Namen, keine Geräte und keine Schreibpfade unter Links. Zulässige interne relative Compilerlinks bleiben erhalten. Python 3.12+ wendet zusätzlich den Tar-`data`-Filter an. Alle Prozessaufrufe erhalten Argumentlisten mit `shell=False`; Configure-Skripte laufen als ausdrücklich ausgewählte Upstream-Dateien mit `/bin/sh`.

Der Build verzichtet unter anderem auf FreeType/Fontconfig, GnuTLS, GStreamer, Audio, X11, OpenGL und Vulkan. Für die eigenen reinen Kernel32-Konsolenprogramme sind diese zusätzlichen Funktionen nicht vorgesehen. Viele grafische Programme, TLS-/Medienfunktionen und .NET-Installer brauchen einen vollständigeren Build und eigene Funktionsprüfungen. Dieses Paket ist deshalb ausdrücklich eine Diagnose-Laufzeit.

## Ablauf und Ergebnis

Unter Windows ist ausschließlich diese Vorbereitung vorgesehen; sie schreibt nichts und führt keine Laufzeit aus:

```text
python tools/wine_runtime_ci.py --plan
```

Die CI führt auf dem Intel-Mac ausdrücklich aus:

```text
python tools/wine_runtime_ci.py --build-and-test --build-root build/wine-runtime --jobs 4
```

Der Buildbereich muss neu oder leer sein. Der Befehl lehnt Windows und ARM-Macs vor Downloads, Verzeichnisanlage und Prozessstart ab. Er baut Bison und Wine, installiert beide in Unterverzeichnisse dieses Bereichs und prüft den Wine-Loader auf ein Intel-Mach-O-Executable.

Der eigene [C-Quellcode](../ci/payload/runtime_smoke.c) wird zweimal ohne CRT und nur mit Kernel32-Importen übersetzt. Ein compile-time Größencheck und der PE-Inspector prüfen jeweils die tatsächliche Architektur. Jedes Programm erzeugt mit `CREATE_NEW` eine eigene Ergebnisdatei, schreibt einen festen Token in diese Datei und auf stdout und beendet sich mit Code 0. Jeder fehlerhafte Zugriff liefert einen anderen Rückgabecode. Die x86-Ausführung findet im selben nachweislich `win64` angelegten Prefix statt.

Beide Starts gehen über `windows_compatibility.py launch`: dieselbe explizite Laufzeit, Herkunftsmarker, Hashprüfungen vor/nach Versionsprobe und keine Shell. Der Builder akzeptiert ein Ergebnis nur bei exaktem Token, identischer Ergebnisdatei, Rückgabecode 0, positivem Launcher-Bericht, erwarteter PE-Architektur/-Hash und tatsächlich abgefragtem Wine 11.0. Der CI-Prefix unterdrückt Mono-/Gecko-Initialisierung; der allgemeine Launcher übernimmt diese DLL-Overrides nicht. Es werden keine fremden Windows-EXEs bezogen oder gestartet.

## Aufbewahrung, Lizenz und Aufwand

Der Workflow bewahrt `wine-11-intel-runtime-proof` sieben Tage auf, auch bei einem gescheiterten Schritt. Das Artefakt enthält den strukturierten Buildbericht, bereinigte Logs, vollständige unmodifizierte Wine-/Bison-Quellarchive, eigene Buildquellen, Fremdlizenzen und bei Erfolg die Diagnose-Laufzeit sowie beide eigenen Programme und Ergebnisdateien. Absolutpfade des Build-, Repository-, Home- und temporären Bereichs werden in Textberichten/Logs ersetzt. Prefix, Sitzungsumgebung und Compiler-Binärarchiv werden nicht hochgeladen.

Wine bleibt LGPL-2.1-or-later; Upstream-COPYING/Notices und vollständige Quelle bleiben beim Runtime-Artefakt. LLVM/MinGW-Lizenzen stehen getrennt dabei; Bison behält GPL-3.0-or-later und seine Upstream-Ausnahmen. Eigene Programme und Werkzeuge stehen unter GPL-3.0-only. Der GPL-Haupttext ersetzt keine Fremdlizenz. Weitergabe des Runtime-Artefakts muss Quelle und Hinweise mit erhalten. Siehe [NOTICE](../NOTICE).

Die drei Archive sind zusammen **160.233.664 Bytes**, rund 153 MiB. Für entpackte Quellen, Compiler, Objektdateien, Prefix und Runtime werden vorläufig etwa **5–8 GB** freier Platz eingeplant; der tatsächliche Spitzenbedarf wurde nicht gemessen. Die erste erfolgreiche Runtime-Prüfung dauerte **3.245,644 Sekunden, rund 54,1 Minuten**, darin **2.433,422 Sekunden, rund 40,6 Minuten**, für Wine-Make mit vier parallelen Jobs. Setup und Artefaktupload kommen hinzu. Der Job endet nach 90 Minuten, der Wine-Make-Schritt nach spätestens 60 Minuten. Im Bericht stehen die gemessenen Schrittzeiten und Toolversionen. Apple-SDK/Host-Image sind dokumentierte, veränderliche Bestandteile; byteidentische Builds auf unterschiedlichen Hostständen sind nicht behauptet.

Das [CI-Artefakt 11691749613](https://github.com/IT-EXPRESS-Bayern/LunarBridge-Windows-Compatibility/actions/runs/38110355646/artifacts/11691749613) umfasst **90.189.404 Bytes**. GitHub-Metadaten und Uploadlog nennen SHA-256 `4d64ac424e15578b1c3f0c61b9dceffa5441e7d804691e0462b83673f75358c6`. Der vollständige Original-ZIP-Digest wurde nach dem Download unabhängig nachgerechnet und bestätigt; alle 109 Originalmitglieder bestanden CRC-, Namens- und Budgetprüfungen. Der selektiv gelesene Buildbericht hat den unabhängig berechneten SHA-256 `9598cd6ecd54f623c9fa5a73b7f85a4d21a0e2859df137d27fee24b6f567ded9`. Laut diesem Bericht misst das enthaltene Runtime-Archiv 53.592.428 Bytes mit SHA-256 `0271fbeca2bc839bd681946a773df3190f7da5e3cf5db81afea44fc3bc2f463a`; dieser Paketwert wurde zunächst auf dem CI-Mac und danach unabhängig aus dem vollständig bezogenen ZIP berechnet. Der x64-Mach-O-Loaderhash und alle 3.677 Runtime-Tar-Mitglieder wurden ausschließlich lesend geprüft. Die vollständigen Wine-/Bison-Archivhashes, bei Wine zusätzlich SHA-512, sowie die erhaltenen Lizenzbytes wurden unabhängig gegen die Quellen geprüft. Fünf Recipe-Dateien sind im Original enthalten; die fehlende sechste ist unten getrennt beschrieben.

Die abschließende Serverprüfung meldet `prefix_cleanup_completed: false`: `wineserver --kill` lieferte Code 1 ohne Ausgabetext. Laut den [Wine-11-Optionsregeln](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/server/main.c#L79) und [Lock-Prüfregeln](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/server/request.c#L664) kann dieser Code auch auftreten, wenn kein Server mehr läuft. Der historische Lauf enthält keine nachfolgende abschließende Wait-Prüfung; sein Aufräumstatus bleibt deshalb unbestätigt. Die beiden bereits belegten PE-Ergebnisse bleiben erfolgreich.

Das Runtime-Archiv wurde für den CI-Installationsprefix konfiguriert. Seine Verlagerung auf einen anderen Rechner ist ungeprüft. Für einen späteren vollständigen App-Build bleiben zusätzliche Bibliotheken, ausgewählte Programme, Installer-Laufzeiten und reale Funktionstests offen.

## Vollständigkeit des Buildrezepts beim Upload

Im Originalartefakt des erfolgreichen Runtime-Laufs fehlte `recipe/.github/workflows/wine-runtime.yml`: Der Upload schloss versteckte Ordner aus. Die fünf übrigen Recipe-Dateien, vollständige Wine-/Bison-Quellarchive und Fremdlizenzen sind davon getrennt vorhanden. Eine Ergänzung muss die fehlende Datei aus dem exakten Build-Commit `3dcc431371543d80b69de3f0deacf979bb3b1ccd` lesen und ihren Hash mit `BUILD_REPORT.json` vergleichen. Ein so ergänztes Downloadpaket benötigt eine neue Prüfsumme und einen ausdrücklichen Ergänzungsnachweis; es darf nicht als unverändertes GitHub-Original erscheinen.

Der Runtime-Upload verwendet jetzt `include-hidden-files: true` auf dem ausdrücklich vorbereiteten Outputbereich. Ein kurzer separater `Wine runtime recipe archive`-Workflow prüft Änderungen am Uploadrezept mit sechs ausgewählten Recipe-Dateien und den beiden eigenen Lizenz-/Hinweisdateien. Workflowänderungen allein lösen diesen Paketcheck aus; neue Runtime-Quellen oder ein manueller Dispatch starten weiterhin den vollständigen Wine-Build. Der Paketcheck baut oder startet Wine nicht und darf keine PE- oder Hardwarefunktion behaupten.

Der [korrigierte Upload-Lauf 38115060446](https://github.com/IT-EXPRESS-Bayern/LunarBridge-Windows-Compatibility/actions/runs/38115060446) am Quellstand `943833ef66ebdf1244c2869f11d2cb60ae708987` ist erfolgreich. Sein wirklich heruntergeladenes Artefakt enthält die versteckte Workflowdatei, alle sechs ausgewählten Rezeptquellen und zwei Hinweise. Alle acht Dateien wurden bytegleich mit diesem Git-Commit verglichen; ZIP-SHA und CRC sind unabhängig geprüft. [RECIPE_UPLOAD_VALIDATION.json](RECIPE_UPLOAD_VALIDATION.json) hält den Uploadnachweis fest. Ein zusätzlicher portabler Lauf besteht weiterhin 79 Tests je Windows-/Intel-macOS-Host.

Das vollständig geprüfte, ausdrücklich ergänzte Downloadpaket umfasst **90,189,414 Bytes** und hat SHA-256 `7676de1881e3c813adc3bc1e762907a2d981ecf8a5b2897b778bd81086e682b6`. Alle 109 Originalmitglieder bleiben inhaltlich unverändert. Hinzu kommen nur die historische Workflowdatei und `SOURCE-SUPPLEMENT.json`; alle sechs Rezeptquellen entsprechen dem ursprünglichen Runtime-Build-Commit. [PACKAGE_VALIDATION.json](PACKAGE_VALIDATION.json) enthält Original- und Ausgabedigest, die tatsächlichen Quellen-/Lizenzprüfungen und die weiterhin offenen Funktionsgrenzen.
