"""
Datendownload-Modul für Geoportal NRW
Lädt automatisch Gelände-, Gebäude- und OSM-Daten basierend auf einer Bounding Box
"""

import logging
import requests
import json
import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlencode, quote
import xml.etree.ElementTree as ET
import geopandas as gpd
from shapely.geometry import box
import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
import numpy as np
import zipfile
import io
from pyproj import Transformer


class DataDownloader:
    """Download-Manager für NRW Geoportal Daten"""
    
    # OpenGeoData NRW URLs
    LOD2_BASE_URL = "https://www.opengeodata.nrw.de/produkte/geobasis/3dg/lod2_gml/lod2_gml/"
    DGM_BASE_URL = "https://www.opengeodata.nrw.de/produkte/geobasis/hm/dgm1_xyz/dgm1_xyz/"
    
    # Overpass API für OSM Daten
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.raw_dir = self.work_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        
        # Verzeichnisse für verschiedene Datentypen
        self.terrain_dir = self.raw_dir / "terrain"
        self.buildings_dir = self.raw_dir / "buildings"
        self.osm_dir = self.raw_dir / "osm"
        
        for d in [self.terrain_dir, self.buildings_dir, self.osm_dir]:
            d.mkdir(parents=True, exist_ok=True)
    
    def download_terrain(self, bbox: Tuple[float, float, float, float]) -> Path:
        """
        Lädt DGM (Digitales Geländemodell) von OpenGeoData NRW
        
        Args:
            bbox: (min_x, min_y, max_x, max_y) in EPSG:25832
        
        Returns:
            Path zur heruntergeladenen GeoTIFF-Datei
        """
        self.logger.info(f"Lade Geländedaten für Bbox: {bbox}")
        
        output_file = self.terrain_dir / "gelaende.tif"
        
        # Berechne Kacheln die benötigt werden (1km x 1km Kacheln)
        tiles = self._calculate_dgm_tiles(bbox)
        
        if not tiles:
            self.logger.warning("Keine DGM-Kacheln für diese Bounding Box gefunden")
            return self._create_synthetic_terrain(bbox, output_file)
        
        # Lade alle benötigten Kacheln
        all_points = []
        
        for tile in tiles:
            try:
                points = self._download_dgm_tile(tile)
                if points:
                    all_points.extend(points)
            except Exception as e:
                self.logger.warning(f"Fehler beim Download der Kachel {tile}: {e}")
        
        if all_points:
            # Konvertiere XYZ-Punkte zu GeoTIFF
            return self._xyz_to_geotiff(all_points, bbox, output_file)
        else:
            return self._create_synthetic_terrain(bbox, output_file)
    
    def _calculate_dgm_tiles(self, bbox: Tuple[float, float, float, float]) -> List[str]:
        """
        Berechnet welche DGM-Kacheln für die Bounding Box benötigt werden
        
        Args:
            bbox: Bounding Box in EPSG:25832
        
        Returns:
            Liste von Kachel-IDs
        """
        min_x, min_y, max_x, max_y = bbox
        
        # Prüfe ob Koordinaten plausibel sind (EPSG:25832 für NRW)
        # NRW liegt etwa zwischen 280000-450000 (X) und 5600000-5800000 (Y)
        if min_x < 100 or max_x < 100 or min_y < 100 or max_y < 100:
            self.logger.error(f"Koordinaten scheinen nicht in EPSG:25832 zu sein: {bbox}")
            self.logger.error("Bitte verwenden Sie 'python convert_coordinates.py' zur Konvertierung von WGS84")
            return []
        
        # DGM1 Kacheln sind 1km x 1km groß
        # Kachel-ID Format: dgm1_32xxx_yyyy_1_nw.xyz
        tiles = []
        
        # Runde auf Kilometer
        start_x = int(min_x / 1000)
        end_x = int(max_x / 1000) + 1
        start_y = int(min_y / 1000)
        end_y = int(max_y / 1000) + 1
        
        for x in range(start_x, end_x):
            for y in range(start_y, end_y):
                tile_name = f"dgm1_32{x:03d}_{y:04d}_1_nw.xyz"
                tiles.append(tile_name)
        
        self.logger.info(f"Benötige {len(tiles)} DGM-Kacheln")
        return tiles
    
    def _download_dgm_tile(self, tile_name: str) -> List[Tuple[float, float, float]]:
        """
        Lädt eine einzelne DGM-Kachel
        
        Args:
            tile_name: Name der Kachel
        
        Returns:
            Liste von (x, y, z) Punkten
        """
        url = f"{self.DGM_BASE_URL}{tile_name}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse XYZ Format
            points = []
            for line in response.text.strip().split('\n'):
                parts = line.strip().split()
                if len(parts) == 3:
                    x, y, z = map(float, parts)
                    points.append((x, y, z))
            
            self.logger.debug(f"Kachel {tile_name}: {len(points)} Punkte geladen")
            return points
            
        except Exception as e:
            self.logger.error(f"Fehler beim Download von {tile_name}: {e}")
            return []
    
    def _xyz_to_geotiff(self, points: List[Tuple[float, float, float]], 
                       bbox: Tuple[float, float, float, float],
                       output_file: Path) -> Path:
        """
        Konvertiert XYZ-Punkte zu GeoTIFF
        
        Args:
            points: Liste von (x, y, z) Punkten
            bbox: Bounding Box
            output_file: Ausgabedatei
        
        Returns:
            Path zur GeoTIFF-Datei
        """
        self.logger.info(f"Konvertiere {len(points)} Punkte zu GeoTIFF")
        
        # Erstelle Arrays
        points_array = np.array(points)
        x_coords = points_array[:, 0]
        y_coords = points_array[:, 1]
        z_coords = points_array[:, 2]
        
        # Bestimme Grid-Größe (1m Auflösung)
        min_x, min_y, max_x, max_y = bbox
        width = int(max_x - min_x) + 1
        height = int(max_y - min_y) + 1
        
        # Erstelle leeres Grid
        grid = np.full((height, width), np.nan, dtype=np.float32)
        
        # Fülle Grid mit Punkten
        for x, y, z in points:
            if min_x <= x <= max_x and min_y <= y <= max_y:
                col = int(x - min_x)
                row = height - 1 - int(y - min_y)  # Y-Achse invertieren
                if 0 <= row < height and 0 <= col < width:
                    grid[row, col] = z
        
        # Interpoliere fehlende Werte
        from scipy.interpolate import griddata
        
        # Erstelle Maske für gültige Werte
        valid_mask = ~np.isnan(grid)
        if np.sum(valid_mask) > 0:
            # Erstelle Koordinaten-Grid
            rows, cols = np.meshgrid(range(height), range(width), indexing='ij')
            
            # Extrahiere gültige Punkte
            valid_points = np.column_stack([rows[valid_mask], cols[valid_mask]])
            valid_values = grid[valid_mask]
            
            # Interpoliere
            grid_filled = griddata(valid_points, valid_values, 
                                 (rows, cols), method='linear')
            
            # Fülle verbleibende NaN mit nearest neighbor
            remaining_nan = np.isnan(grid_filled)
            if np.any(remaining_nan):
                grid_filled[remaining_nan] = griddata(valid_points, valid_values,
                                                    (rows[remaining_nan], cols[remaining_nan]),
                                                    method='nearest')
        else:
            # Fallback: konstante Höhe
            grid_filled = np.full_like(grid, 50.0)
        
        # Erstelle GeoTIFF
        transform = rasterio.transform.from_bounds(
            min_x, min_y, max_x, max_y,
            width, height
        )
        
        with rasterio.open(
            output_file,
            'w',
            driver='GTiff',
            height=height,
            width=width,
            count=1,
            dtype=grid_filled.dtype,
            crs='EPSG:25832',
            transform=transform
        ) as dst:
            dst.write(grid_filled, 1)
        
        self.logger.info(f"Geländedaten gespeichert: {output_file}")
        return output_file
    
    def _create_synthetic_terrain(self, bbox: Tuple[float, float, float, float], output_file: Path) -> Path:
        """Erstellt ein synthetisches flaches Terrain als Fallback"""
        self.logger.warning("Erstelle synthetisches Terrain als Fallback")
        
        # Erstelle ein 100x100 Grid
        width, height = 100, 100
        
        # Transformationsmatrix
        transform = rasterio.transform.from_bounds(
            bbox[0], bbox[1], bbox[2], bbox[3],
            width, height
        )
        
        # Erstelle flaches Terrain mit leichtem Rauschen
        np.random.seed(42)
        elevation = np.ones((height, width)) * 50.0  # 50m Basishöhe
        elevation += np.random.normal(0, 0.5, (height, width))  # Leichtes Rauschen
        
        # Speichere als GeoTIFF
        with rasterio.open(
            output_file,
            'w',
            driver='GTiff',
            height=height,
            width=width,
            count=1,
            dtype=elevation.dtype,
            crs='EPSG:25832',
            transform=transform
        ) as dst:
            dst.write(elevation, 1)
        
        return output_file
    
    def download_buildings(self, bbox: Tuple[float, float, float, float]) -> List[Path]:
        """
        Lädt LOD2 Gebäudedaten (CityGML) von OpenGeoData NRW
        
        Args:
            bbox: (min_x, min_y, max_x, max_y) in EPSG:25832
        
        Returns:
            Liste der heruntergeladenen CityGML-Dateien
        """
        self.logger.info("Lade Gebäudedaten (LOD2 CityGML)...")
        
        # Berechne benötigte Kacheln
        tiles = self._calculate_lod2_tiles(bbox)
        
        if not tiles:
            self.logger.warning("Keine LOD2-Kacheln für diese Bounding Box gefunden")
            return self._create_empty_citygml(self.buildings_dir / "empty.gml")
        
        downloaded_files = []
        
        for tile in tiles:
            try:
                file_path = self._download_lod2_tile(tile)
                if file_path:
                    downloaded_files.append(file_path)
            except Exception as e:
                self.logger.warning(f"Fehler beim Download der Kachel {tile}: {e}")
        
        if not downloaded_files:
            return self._create_empty_citygml(self.buildings_dir / "empty.gml")
        
        return downloaded_files
    
    def _calculate_lod2_tiles(self, bbox: Tuple[float, float, float, float]) -> List[str]:
        """
        Berechnet welche LOD2-Kacheln für die Bounding Box benötigt werden
        
        Args:
            bbox: Bounding Box in EPSG:25832
        
        Returns:
            Liste von Kachel-Namen
        """
        min_x, min_y, max_x, max_y = bbox
        
        # Prüfe ob Koordinaten plausibel sind (EPSG:25832 für NRW)
        if min_x < 100 or max_x < 100 or min_y < 100 or max_y < 100:
            self.logger.error(f"Koordinaten scheinen nicht in EPSG:25832 zu sein: {bbox}")
            self.logger.error("Bitte verwenden Sie 'python convert_coordinates.py' zur Konvertierung von WGS84")
            return []
        
        # LOD2 Kacheln sind 1km x 1km groß
        # Format: LoD2_32{xxx}_{yyyy}_1_NW.gml
        tiles = []
        
        # Runde auf Kilometer
        start_x = int(min_x / 1000)
        end_x = int(max_x / 1000) + 1
        start_y = int(min_y / 1000)
        end_y = int(max_y / 1000) + 1
        
        for x in range(start_x, end_x):
            for y in range(start_y, end_y):
                tile_name = f"LoD2_32{x:03d}_{y:04d}_1_NW.gml"
                tiles.append(tile_name)
        
        self.logger.info(f"Benötige {len(tiles)} LOD2-Kacheln")
        return tiles
    
    def _download_lod2_tile(self, tile_name: str) -> Optional[Path]:
        """
        Lädt eine einzelne LOD2-Kachel
        
        Args:
            tile_name: Name der Kachel
        
        Returns:
            Path zur heruntergeladenen Datei oder None
        """
        url = f"{self.LOD2_BASE_URL}{tile_name}"
        output_file = self.buildings_dir / tile_name
        
        try:
            self.logger.debug(f"Lade LOD2-Kachel: {url}")
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            # Speichere GML-Datei
            with open(output_file, 'wb') as f:
                f.write(response.content)
            
            self.logger.info(f"LOD2-Kachel gespeichert: {output_file}")
            return output_file
            
        except Exception as e:
            self.logger.error(f"Fehler beim Download von {tile_name}: {e}")
            return None
    
    def _create_empty_citygml(self, output_file: Path) -> List[Path]:
        """Erstellt eine leere CityGML-Datei als Platzhalter"""
        citygml_template = """<?xml version="1.0" encoding="UTF-8"?>
<core:CityModel xmlns:core="http://www.opengis.net/citygml/2.0"
                xmlns:bldg="http://www.opengis.net/citygml/building/2.0"
                xmlns:gml="http://www.opengis.net/gml">
    <gml:name>Empty Building Model</gml:name>
</core:CityModel>"""
        
        with open(output_file, 'w') as f:
            f.write(citygml_template)
        
        return [output_file]
    
    def download_osm_data(self, bbox: Tuple[float, float, float, float]) -> Dict[str, Path]:
        """
        Lädt OSM-Daten (Straßen, Gewässer, Vegetation) über Overpass API
        
        Args:
            bbox: (min_x, min_y, max_x, max_y) in EPSG:25832
        
        Returns:
            Dictionary mit Pfaden zu den GeoJSON-Dateien
        """
        self.logger.info("Lade OSM-Daten...")
        
        # Konvertiere EPSG:25832 zu WGS84 für Overpass API
        transformer = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
        
        # Transformiere Eckpunkte
        min_lon, min_lat = transformer.transform(bbox[0], bbox[1])
        max_lon, max_lat = transformer.transform(bbox[2], bbox[3])
        wgs84_bbox = (min_lat, min_lon, max_lat, max_lon)
        
        results = {}
        
        # Download Straßen
        results['streets'] = self._download_osm_streets(wgs84_bbox)
        
        # Download Gewässer
        results['water'] = self._download_osm_water(wgs84_bbox)
        
        # Download Vegetation
        results['vegetation'] = self._download_osm_vegetation(wgs84_bbox)
        
        return results
    
    def _download_osm_streets(self, bbox: Tuple[float, float, float, float]) -> Path:
        """Lädt Straßendaten von OSM"""
        output_file = self.osm_dir / "strassen.geojson"
        
        # Overpass QL Query für Straßen
        query = f"""
        [out:json][timeout:60];
        (
          way["highway"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        );
        out body;
        >;
        out skel qt;
        """
        
        try:
            response = requests.post(
                self.OVERPASS_URL,
                data={'data': query},
                timeout=60
            )
            response.raise_for_status()
            
            # Konvertiere OSM JSON zu GeoJSON
            osm_data = response.json()
            geojson = self._osm_to_geojson(osm_data, 'highway')
            
            # Speichere als GeoJSON
            with open(output_file, 'w') as f:
                json.dump(geojson, f)
            
            self.logger.info(f"Straßendaten gespeichert: {output_file}")
            return output_file
            
        except Exception as e:
            self.logger.error(f"Fehler beim Download der Straßendaten: {e}")
            return self._create_empty_geojson(output_file, "streets")
    
    def _download_osm_water(self, bbox: Tuple[float, float, float, float]) -> Path:
        """Lädt Gewässerdaten von OSM"""
        output_file = self.osm_dir / "gewaesser.geojson"
        
        # Overpass QL Query für Gewässer
        query = f"""
        [out:json][timeout:60];
        (
          way["natural"="water"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          way["waterway"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          relation["natural"="water"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        );
        out body;
        >;
        out skel qt;
        """
        
        try:
            response = requests.post(
                self.OVERPASS_URL,
                data={'data': query},
                timeout=60
            )
            response.raise_for_status()
            
            osm_data = response.json()
            geojson = self._osm_to_geojson(osm_data, 'water')
            
            with open(output_file, 'w') as f:
                json.dump(geojson, f)
            
            self.logger.info(f"Gewässerdaten gespeichert: {output_file}")
            return output_file
            
        except Exception as e:
            self.logger.error(f"Fehler beim Download der Gewässerdaten: {e}")
            return self._create_empty_geojson(output_file, "water")
    
    def _download_osm_vegetation(self, bbox: Tuple[float, float, float, float]) -> Path:
        """Lädt Vegetationsdaten von OSM"""
        output_file = self.osm_dir / "vegetation.geojson"
        
        # Overpass QL Query für Vegetation
        query = f"""
        [out:json][timeout:60];
        (
          way["landuse"~"forest|grass|meadow|park"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          way["natural"~"wood|grassland|scrub"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
          way["leisure"="park"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        );
        out body;
        >;
        out skel qt;
        """
        
        try:
            response = requests.post(
                self.OVERPASS_URL,
                data={'data': query},
                timeout=60
            )
            response.raise_for_status()
            
            osm_data = response.json()
            geojson = self._osm_to_geojson(osm_data, 'vegetation')
            
            with open(output_file, 'w') as f:
                json.dump(geojson, f)
            
            self.logger.info(f"Vegetationsdaten gespeichert: {output_file}")
            return output_file
            
        except Exception as e:
            self.logger.error(f"Fehler beim Download der Vegetationsdaten: {e}")
            return self._create_empty_geojson(output_file, "vegetation")
    
    def _osm_to_geojson(self, osm_data: dict, feature_type: str) -> dict:
        """Konvertiert OSM JSON zu GeoJSON"""
        features = []
        nodes = {}
        
        # Sammle alle Nodes
        for element in osm_data.get('elements', []):
            if element['type'] == 'node':
                nodes[element['id']] = [element['lon'], element['lat']]
        
        # Verarbeite Ways
        for element in osm_data.get('elements', []):
            if element['type'] == 'way':
                coords = []
                for node_id in element.get('nodes', []):
                    if node_id in nodes:
                        coords.append(nodes[node_id])
                
                if len(coords) >= 2:
                    # Erstelle LineString oder Polygon
                    geometry_type = "Polygon" if coords[0] == coords[-1] and len(coords) > 3 else "LineString"
                    
                    feature = {
                        "type": "Feature",
                        "properties": {
                            "type": feature_type,
                            "osm_id": element['id'],
                            **element.get('tags', {})
                        },
                        "geometry": {
                            "type": geometry_type,
                            "coordinates": [coords] if geometry_type == "Polygon" else coords
                        }
                    }
                    features.append(feature)
        
        return {
            "type": "FeatureCollection",
            "features": features
        }
    
    def _create_empty_geojson(self, output_file: Path, feature_type: str) -> Path:
        """Erstellt eine leere GeoJSON-Datei als Platzhalter"""
        empty_geojson = {
            "type": "FeatureCollection",
            "features": []
        }
        
        with open(output_file, 'w') as f:
            json.dump(empty_geojson, f)
        
        return output_file