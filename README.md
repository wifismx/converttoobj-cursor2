# NRW 3D Model Generator

Ein Python-Tool zur automatischen Generierung wasserdichter 3D-Modelle im OBJ-Format aus Geodaten des OpenGeoData NRW Portals.

## Features

- ✅ Automatischer Download von Geodaten aus OpenGeoData NRW
- ✅ LOD2 Gebäudedaten (CityGML) Integration
- ✅ Digitales Geländemodell (DGM1) Verarbeitung
- ✅ OpenStreetMap Datenintegration (Straßen, Gewässer, Vegetation)
- ✅ Exakte Bounding-Box Zuschneidung
- ✅ Koordinatensystem EPSG:25832 (ETRS89 / UTM zone 32N)
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

### Koordinaten-Konvertierung

Das Tool erwartet Koordinaten im System **EPSG:25832** (UTM Zone 32N). Wenn Sie WGS84-Koordinaten (Länge/Breite) haben, nutzen Sie das Konvertierungsskript:

```bash
# Konvertiere WGS84 Bounding Box zu EPSG:25832
python convert_coordinates.py "6.448572,51.667549,6.46076,51.675108"

# Konvertiere einzelnen Punkt mit 500m Radius
python convert_coordinates.py "6.95,50.94" --expand 500
```

### Grundlegende Verwendung

```bash
# Mit EPSG:25832 Koordinaten
python nrw_3d_generator.py "min_x,min_y,max_x,max_y"

# Beispiel für Köln Dom Umgebung
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

### OpenGeoData NRW (https://www.opengeodata.nrw.de)
- **Digitales Geländemodell (DGM1)**: 1m Auflösung, XYZ-Format
  - Kacheln: 1km x 1km
  - Format: `dgm1_32{xxx}_{yyyy}_1_nw.xyz`
- **3D-Gebäudemodelle (LOD2)**: CityGML Format
  - Kacheln: 1km x 1km  
  - Format: `LoD2_32{xxx}_{yyyy}_1_NW.gml`

### OpenStreetMap (via Overpass API)
- **Straßen**: Alle Straßentypen mit automatischer Breitenerkennung
- **Gewässer**: Flüsse, Seen, Teiche
- **Vegetation**: Wälder, Parks, Grünflächen

## Verarbeitungsphasen

### Phase 1: Datendownload
- Download der Geländedaten (XYZ → GeoTIFF)
- Download der Gebäudedaten (CityGML)
- Download der OSM-Daten (GeoJSON)

### Phase 2: Datenverarbeitung
- Koordinatentransformation nach EPSG:25832
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
5. **Koordinaten**: Verwenden Sie das Konvertierungsskript für WGS84-Koordinaten

## Fehlerbehebung

### "Keine Daten gefunden"
- Überprüfen Sie, ob die Bounding Box in NRW liegt
- Koordinaten müssen in EPSG:25832 sein (nutzen Sie `convert_coordinates.py`)

### "Mesh nicht wasserdicht"
- Erhöhen Sie die `--foundation-depth`
- Reduzieren Sie die `--terrain-resolution`

### "Speicherfehler"
- Verkleinern Sie die Bounding Box
- Erhöhen Sie die Terrain-Auflösung

### "IndexError bei Mesh-Erstellung"
- Das Tool hat Fallback-Mechanismen für fehlerhafte Meshes
- Versuchen Sie eine andere Bounding Box

## Beispiel-Koordinaten (EPSG:25832)

- **Köln Dom**: 356300,5644700,357300,5645700 (1km²)
- **Düsseldorf Altstadt**: 338000,5678000,339000,5679000 (1km²)
- **Bonn Zentrum**: 364500,5619500,365500,5620500 (1km²)
- **Aachen Dom**: 293500,5629500,294500,5630500 (1km²)
- **Münster Dom**: 403500,5756500,404500,5757500 (1km²)

Für kleinere Bereiche (500m x 500m):
```bash
# Köln Dom (500m Radius)
python nrw_3d_generator.py "356550,5644950,357050,5645450"
```

## Lizenz

MIT License - Siehe LICENSE Datei

## Beiträge

Beiträge sind willkommen! Bitte erstellen Sie einen Pull Request oder öffnen Sie ein Issue.

## Bekannte Einschränkungen

- Die Verfügbarkeit von LOD2-Gebäudedaten variiert je nach Region
- DGM1-Daten sind nur für NRW verfügbar
- Große Bereiche (>10 km²) können zu Speicherproblemen führen
- OSM-Daten können unvollständig sein

## Kontakt

Bei Fragen oder Problemen erstellen Sie bitte ein Issue auf GitHub.