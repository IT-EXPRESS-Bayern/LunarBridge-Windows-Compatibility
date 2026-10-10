# Kompatibilität und Quellen

Stand der Quellenprüfung: 10. Oktober 2026. Ziel ist die native Intel-Installation auf Samsung Galaxy Book5 Pro16 NP960XHA-KG3DE, Core Ultra 5 226V und Arc 130V Xe2. Weder der macOS-Start dieses Rechners noch eine native GPU-Beschleunigung sind bereits bestätigt.

## Wine und 32/64 Bit

Wine übersetzt Windows-APIs in Funktionen des Wirtsystems; dafür ist keine Windows-VM vorgesehen. Der eigene Code ruft eine bewusst ausgewählte Wine-Datei als separates Programm auf. Die [Wine-11.0-README](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/README.md) beschreibt den macOS-Unterbau sowie das Starten mit einer vollständigen EXE-Pfadangabe. Sie ist keine Zertifizierung dieses Samsung-Laptops oder einer konkreten Tahoe-Konfiguration.

Die [Wine-11.0-Ankündigung](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/ANNOUNCE.md) bezeichnet den neuen WoW64-Modus als unterstützt. Er benötigt einen 64-Bit-Prefix; reine `win32`-Prefixes sind für diesen Modus ungeeignet. Wine 11 verwendet einen gemeinsamen `wine`-Loader anstelle eines separaten `wine64`. Deshalb fordert unser x86-Startpfad eine ausgewählte Wine-Version ab 11. Eine bestandene Versionsabfrage bestätigt weder die konkrete WoW64-Konfiguration noch die Funktion der App; beides bleibt ein echter Laufzeittest.

WineHQ-GitLab-Wiki und Release-Seite waren bei dieser Prüfung zugriffsgeschützt. Die gelesenen Release-Dokumente stammen aus dem Wine-Mirror, festgelegt auf den zu `wine-11.0` gehörenden Commit `db11d0fe6a169c457e23d007e20404643d067aa8`. Die [Lizenz dieses Stands](https://github.com/wine-mirror/wine/blob/db11d0fe6a169c457e23d007e20404643d067aa8/LICENSE) lautet LGPL-2.1-or-later. Das Repository verteilt diese Laufzeit nicht.

## Anforderungen einer App

| Beobachtung | Was der Inspector meldet | Was noch geprüft werden muss |
| --- | --- | --- |
| x64-PE | Intel-x64-Kandidat | Windows-APIs und echte Wine-Ausführung |
| x86-PE | WoW64 erforderlich | x86-Loader und echte 32-Bit-App im 64-Bit-Prefix |
| CLR-Header oder `mscoree.dll` | Managed-Runtime-Familie unbestätigt | Framework-Version, Wine Mono beziehungsweise geeignete .NET-Laufzeit |
| VC-/UCRT-Importe | Kandidat für Laufzeitfamilie | tatsächlich benötigte Version und zulässiger Installer |
| Direct3D/OpenGL/Vulkan-Importe | sichtbare Grafikabhängigkeit | Host-Treiber, API-Funktionen und echter Render-Test |
| DLL-/Systemflag oder fremdes Subsystem | Startblocker | keine automatische Umdeutung in ein Userland-Programm |
| Keine sichtbaren Grafikimporte | keine statische Grafikbeobachtung | dynamische Importe und enthaltene Komponenten weiterhin unbekannt |

Die PE-Strukturprüfung folgt der [Microsoft-PE-Spezifikation](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format). Sie berücksichtigt unterschiedliche optionale Header, virtuelle gegenüber Dateiadressen, Abschnittsgrenzen und Importtabellen. Es werden keine Importfunktionen ausgeführt. Gewöhnliche Importnamen sind keine vollständige Liste aller benötigten Funktionen; es gibt keine automatische DLL-Beschaffung oder Runtime-Installation.

## Grafik und Tahoe

Wine allein ergänzt keinen fehlenden macOS-Grafiktreiber. Der [CrossOver-Mac-Leitfaden](https://support.codeweavers.com/en_US/crossover-mac-user-guide) unterscheidet WineD3D, DXVK, DXMT und D3DMetal als Grafikpfade. Diese Übersetzungsschichten benötigen ihren jeweiligen Host-Unterbau. [DXMT](https://github.com/3Shain/dxmt) übersetzt Direct3D 10/11 in Metal; seine Existenz beweist keine Unterstützung einer Intel-Xe2-iGPU auf unserem Hackintosh.

Apple beschreibt die Evaluation unveränderter Windows-Spiele im [Game Porting Toolkit](https://developer.apple.com/games/game-porting-toolkit/) ausdrücklich für Apple Silicon. Daraus folgt kein fertiger Intel-Lunar-Lake-Pfad. Dieses Modul lädt weder das Toolkit noch Metal-Wrapper und verändert keine Grafik-Registry oder DLL-Overrides.

Als kommerzieller Vergleich nennt die [CodeWeavers-Kompatibilitätstabelle](https://www.codeweavers.com/crossover/#requirements) Tahoe-Unterstützung ab CrossOver 25.1.1. Das betrifft das unterstützte Produkt auf dessen passenden Mac-Systemen. Es ist keine Hardwarefreigabe für NP960XHA-KG3DE, und dieses Projekt kauft, integriert oder verteilt CrossOver nicht.

## Hardwaregrenze

Samsung Settings, Kamerafunktionen, Firmwarezugriffe und andere herstellerspezifische Dienste können Windows-Treiber und System-APIs benötigen. Ein EXE-Start liefert diese Hardwareanbindung nicht automatisch. Wine arbeitet im Userland; die grundsätzliche Trennung zum Host-Kernel ist auch in der [WineHQ-Erklärung zu Kernel-Treibern](https://list.winehq.org/hyperkitty/list/wine-bugs%40list.winehq.org/thread/RNMLZBQCE2VSMS43ATR624OTZTWWXUEI/) beschrieben. Der Inspector blockiert erkennbare Windows-System-/Kernel-Images; er kann verborgene Treiber in einem Installer nicht ausschließen.

