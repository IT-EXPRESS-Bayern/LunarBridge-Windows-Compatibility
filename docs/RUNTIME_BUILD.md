# Echter Wine-Lauf auf dem Intel-macOS-CI-Host

Der separate Workflow `Real Wine 11 runtime on Intel macOS` baut Wine 11.0 auf `macos-26-intel` und muss zwei eigene Windows-Konsolenprogramme ausführen: ein PE32+-x64-Programm und ein PE32-x86-Programm im neuen WoW64-Modus. Der bisher veröffentlichte erfolgreiche Prüflauf in [CI_VALIDATION.json](CI_VALIDATION.json) umfasst die vorherigen 49 synthetischen Tests. Er bestätigt diesen neuen Build noch nicht. Ein tatsächliches neues Ergebnis steht erst im `BUILD_REPORT.json` eines ausgeführten Runtime-Workflows.

Der Host ist ein fremder Intel-Mac. Erfolgreiche Programme dort bestätigen weder den nativen Samsung-Start noch Arc-130V-Beschleunigung oder eine Nutzeranwendung. Der Testbuild enthält keine Direct3D-, Metal-, OpenGL- oder Vulkan-Qualifizierung.

## Feste Quellen und Abhängigkeiten

Die ausführbare Rezeptur liest [ci/runtime-pins.json](../ci/runtime-pins.json). Jeder Bezug verwendet HTTPS, eine erlaubte Primärquelle, eine feste erwartete Dateigröße und SHA-256. Wine wird zusätzlich gegen SHA-512 geprüft. Die Werte wurden aus Upstream-Metadaten beziehungsweise dem bezogenen GNU-Archiv abgeglichen; die CI berechnet die Hashes jedes Downloads erneut.

| Bestandteil | Festgelegter Stand | Primärquelle und Nachweis |
| --- | --- | --- |
| Wine | 11.0, Quellcommit `db11d0fe6a169c457e23d007e20404643d067aa8` | [offizielles Quellarchiv](https://dl.winehq.org/wine/source/11.0/wine-11.0.tar.xz), [offizielle SHA-512-Liste](https://dl.winehq.org/wine/source/11.0/sha512sums.asc), [zugehörige Configure-Quelle](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/configure.ac) |
| LLVM-MinGW | Release 20260908, LLVM 23.1.1, Rezeptcommit `030097eeee87fcfd0f3bfe536b21cbd6e5d3b324` | [Maintainer-Release](https://github.com/mstorsjo/llvm-mingw/releases/tag/20260908), [Release-Asset-Metadaten mit SHA-256](https://api.github.com/repos/mstorsjo/llvm-mingw/releases/tags/20260908), [gepinntes Buildrezept](https://github.com/mstorsjo/llvm-mingw/tree/030097eeee87fcfd0f3bfe536b21cbd6e5d3b324) |
| GNU Bison | 3.8.2, SHA-256 `9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2` | [GNU-Quellarchiv](https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz); unter Windows bezogen und nachgerechnet |
| Python | 3.12.14 im Runtime-Workflow | [offizieller Actions-Python-Build](https://github.com/actions/python-versions/releases/tag/3.12.14-31661455385), fest gepinnte `setup-python`-Action |
| Native Werkzeuge | Apple clang/SDK, make, flex ab 2.5.33 und m4 des CI-Images | Vor dem Build abgefragt, im Bericht festgehalten; kein Homebrew- oder Systeminstallationsschritt |

Wine verlangt Bison ab Version 3.0; ein älterer Systemparser reicht nicht. Deshalb wird Bison aus der festen GNU-Quelle nur in den eigenen Buildbereich installiert. LLVM-MinGW liefert die x64-/i686-PE-Compiler; Wine verwendet den nativen 64-Bit-Apple-Compiler für seinen Unix-Unterbau. `--enable-archs=i386,x86_64 --with-mingw=llvm-mingw` wählt die neuen kombinierten PE-Architekturen. Der [Wine-11-Releasehinweis](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/ANNOUNCE.md) erklärt den gemeinsamen Loader und `WINEARCH=wow64`.

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

Die drei Archive sind zusammen **160.233.664 Bytes**, rund 153 MiB. Für entpackte Quellen, Compiler, Objektdateien, Prefix und Runtime werden vorläufig etwa **5–8 GB** freier Platz und **20–60 Minuten** Buildzeit eingeplant; diese Schätzungen sind vor einem erfolgreichen Lauf nicht gemessen. Der Job endet nach 90 Minuten, der Wine-Make-Schritt nach spätestens 60 Minuten. Im Bericht stehen die tatsächlich gemessenen Schrittzeiten und Toolversionen. Apple-SDK/Host-Image sind dokumentierte, veränderliche Bestandteile; byteidentische Builds auf unterschiedlichen Hostständen sind nicht behauptet.

Das Runtime-Archiv wurde für den CI-Installationsprefix konfiguriert. Seine Verlagerung auf einen anderen Rechner ist ungeprüft. Für einen späteren vollständigen App-Build bleiben zusätzliche Bibliotheken, ausgewählte Programme, Installer-Laufzeiten und reale Funktionstests offen.
