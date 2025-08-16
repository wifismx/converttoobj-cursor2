# NRW 3D Model Generator

Ein Python-Tool zur automatischen Generierung wasserdichter 3D-Modelle im OBJ-Format aus Geodaten des Geoportals NRW.

## Features

- ✅ Automatischer Download von Geodaten aus dem Geoportal NRW
- ✅ LOD2 Gebäudedaten (CityGML) Integration
- ✅ Digitales Geländemodell (DGM) Verarbeitung
- ✅ OpenStreetMap Datenintegration (Straßen, Gewässer, Vegetation)
- ✅ Exakte Bounding-Box Zuschneidung
- ✅ Reprojektion nach EPSG:25832 (ETRS89 / UTM zone 32N)
- ✅ Wasserdichte 3D-Modell-Generierung
- ✅ OBJ-Export für 3D-Druck und Visualisierung

## Installation

### Voraussetzungen

- Python 3.8 oder höher
- GDAL-Bibliotheken (für Geo-Datenverarbeitung)
- Optional: OpenSCAD (für Boolean-Operationen)

### Installation unter Linux/Mac

```bash
# GDAL installieren
sudo apt-get install gdal-bin libgdal-dev  # Ubuntu/Debian
# oder
brew install gdal  # macOS

# Python-Umgebung erstellen
python3 -m venv venv
source venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

### Installation unter Windows

```powershell
# Python-Umgebung erstellen
python -m venv venv
venv\Scripts\activate

# Abhängigkeiten installieren
pip install -r requirements.txt
```

## Verwendung

### Grundlegende Verwendung

```bash
python nrw_3d_generator.py "min_x,min_y,max_x,max_y"
```

Die Bounding Box muss im Koordinatensystem EPSG:25832 angegeben werden.

### Beispiel für Köln Dom Umgebung

```bash
python nrw_3d_generator.py "356800,5645200,357800,5646200" -o koeln_dom.obj
```

### Erweiterte Optionen

```bash
python nrw_3d_generator.py "min_x,min_y,max_x,max_y" \
    -o output.obj \                    # Ausgabedatei (Standard: modell.obj)
    -w ./work \                        # Arbeitsverzeichnis (Standard: ./work)
    --terrain-resolution 2.0 \         # Terrain-Auflösung in Metern (Standard: 1.0)
    --road-thickness 0.3 \             # Dicke der Straßen in Metern (Standard: 0.2)
    --foundation-depth 15.0 \          # Tiefe des Fundaments (Standard: 10.0)
    --skip-download \                  # Überspringt Download, nutzt existierende Daten
    --skip-validation \                # Überspringt Mesh-Validierung
    -v                                 # Ausführliche Ausgabe
```

### Konfigurationsdatei

Sie können auch eine JSON-Konfigurationsdatei verwenden:

```json
{
    "bbox": "356800,5645200,357800,5646200",
    "output": "koeln_dom.obj",
    "terrain_resolution": 2.0,
    "road_thickness": 0.3,
    "foundation_depth": 15.0
}
```

Verwendung:
```bash
python nrw_3d_generator.py --config config.json
```

## Datenquellen

Das Tool bezieht Daten automatisch von folgenden Quellen:

### Geoportal NRW
- **Digitales Geländemodell (DGM)**: WCS-Service für Höhendaten
- **3D-Gebäudemodelle (LOD2)**: WFS-Service für CityGML-Gebäudedaten

### OpenStreetMap (via Overpass API)
- **Straßen**: Alle Straßentypen mit automatischer Breitenerkennung
- **Gewässer**: Flüsse, Seen, Teiche
- **Vegetation**: Wälder, Parks, Grünflächen

## Verarbeitungsphasen

### Phase 1: Datendownload
- Download der Geländedaten (GeoTIFF)
- Download der Gebäudedaten (CityGML)
- Download der OSM-Daten (GeoJSON)

### Phase 2: Datenverarbeitung
- Reprojektion aller Daten nach EPSG:25832
- Clipping auf die exakte Bounding Box
- CityGML zu OBJ Konvertierung

### Phase 3: 3D-Szenen-Assemblierung
- Terrain-Mesh-Generierung aus DGM
- Gebäude-Platzierung auf Terrain
- Straßen-Extrusion mit konfigurierbarer Dicke
- Gewässer- und Vegetations-Drapierung

### Phase 4: Finalisierung
- Fundament-Erstellung unter dem Terrain
- Boolean-Union aller Meshes
- Geometrie-Validierung und Reparatur
- Export als wasserdichtes OBJ

## Ausgabe

Das Tool generiert:
- `modell.obj` - Hauptmodell im OBJ-Format
- `modell.mtl` - Material-Datei
- Arbeitsverzeichnis mit Zwischenergebnissen:
  - `raw/` - Rohdaten
  - `processed/` - Verarbeitete Daten
  - `buildings/` - Konvertierte Gebäude
  - `terrain/` - Terrain-Mesh
  - `extruded/` - Extrudierte Vektordaten
  - `final/` - Finales Modell

## Modell-Eigenschaften

- **Koordinatensystem**: EPSG:25832 (ETRS89 / UTM zone 32N)
- **Einheiten**: Meter
- **Wasserdicht**: Ja (validiert für 3D-Druck)
- **Format**: Wavefront OBJ

## Tipps für optimale Ergebnisse

1. **Bounding Box Größe**: Beginnen Sie mit kleineren Bereichen (1-2 km²) für Tests
2. **Terrain-Auflösung**: Höhere Werte (2-5m) für größere Gebiete
3. **Vereinfachung**: Das Tool vereinfacht automatisch Meshes über 500.000 Faces
4. **Performance**: Nutzen Sie `--skip-download` für wiederholte Verarbeitung

## Fehlerbehebung

### "Keine Daten gefunden"
- Überprüfen Sie, ob die Bounding Box in NRW liegt
- Koordinaten müssen in EPSG:25832 sein

### "Mesh nicht wasserdicht"
- Erhöhen Sie die `--foundation-depth`
- Reduzieren Sie die `--terrain-resolution`

### "Speicherfehler"
- Verkleinern Sie die Bounding Box
- Erhöhen Sie die Terrain-Auflösung

## Beispiel-Koordinaten (EPSG:25832)

- **Köln Dom**: 356800,5645200,357800,5646200
- **Düsseldorf Altstadt**: 338500,5678500,339500,5679500
- **Bonn Zentrum**: 365000,5620000,366000,5621000

## Lizenz

MIT License - Siehe LICENSE Datei

## Beiträge

Beiträge sind willkommen! Bitte erstellen Sie einen Pull Request oder öffnen Sie ein Issue.

## Kontakt

Bei Fragen oder Problemen erstellen Sie bitte ein Issue auf GitHub.