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


class DataDownloader:
    """Download-Manager für NRW Geoportal Daten"""
    
    # WFS/WCS Endpoints für NRW Geoportal
    WCS_TERRAIN_URL = "https://www.wcs.nrw.de/geobasis/wcs_nw_dgm"
    WFS_BUILDINGS_URL = "https://www.wfs.nrw.de/geobasis/wfs_nw_3d-gebaeudemodell_lod2"
    
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
        Lädt DGM (Digitales Geländemodell) vom WCS Service
        
        Args:
            bbox: (min_x, min_y, max_x, max_y) in EPSG:25832
        
        Returns:
            Path zur heruntergeladenen GeoTIFF-Datei
        """
        self.logger.info(f"Lade Geländedaten für Bbox: {bbox}")
        
        output_file = self.terrain_dir / "gelaende.tif"
        
        # WCS GetCoverage Request Parameter
        params = {
            'SERVICE': 'WCS',
            'VERSION': '2.0.1',
            'REQUEST': 'GetCoverage',
            'COVERAGEID': 'nw_dgm',  # DGM1 für NRW
            'FORMAT': 'image/tiff',
            'SUBSET': f'x({bbox[0]},{bbox[2]})',
            'SUBSETTINGCRS': 'http://www.opengis.net/def/crs/EPSG/0/25832',
            'OUTPUTCRS': 'http://www.opengis.net/def/crs/EPSG/0/25832'
        }
        
        # Y-Achse separat hinzufügen
        url = f"{self.WCS_TERRAIN_URL}?{urlencode(params)}&SUBSET=y({bbox[1]},{bbox[3]})"
        
        try:
            self.logger.debug(f"WCS Request URL: {url}")
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            # Speichere GeoTIFF
            with open(output_file, 'wb') as f:
                f.write(response.content)
            
            self.logger.info(f"Geländedaten gespeichert: {output_file}")
            
            # Validiere die Datei
            with rasterio.open(output_file) as src:
                self.logger.debug(f"GeoTIFF Info - CRS: {src.crs}, Bounds: {src.bounds}, Shape: {src.shape}")
            
            return output_file
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Fehler beim Download der Geländedaten: {e}")
            # Fallback: Erstelle synthetisches flaches Terrain
            return self._create_synthetic_terrain(bbox, output_file)
    
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
        Lädt LOD2 Gebäudedaten (CityGML) vom WFS Service
        
        Args:
            bbox: (min_x, min_y, max_x, max_y) in EPSG:25832
        
        Returns:
            Liste der heruntergeladenen CityGML-Dateien
        """
        self.logger.info("Lade Gebäudedaten (LOD2 CityGML)...")
        
        # WFS GetFeature Request
        bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:25832"
        
        params = {
            'SERVICE': 'WFS',
            'VERSION': '2.0.0',
            'REQUEST': 'GetFeature',
            'TYPENAMES': 'ms:gebaeude_lod2',
            'BBOX': bbox_str,
            'OUTPUTFORMAT': 'application/gml+xml; version=3.2',
            'SRSNAME': 'EPSG:25832'
        }
        
        output_file = self.buildings_dir / "buildings.gml"
        
        try:
            url = f"{self.WFS_BUILDINGS_URL}?{urlencode(params)}"
            self.logger.debug(f"WFS Request URL: {url}")
            
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            
            # Speichere CityGML
            with open(output_file, 'wb') as f:
                f.write(response.content)
            
            self.logger.info(f"Gebäudedaten gespeichert: {output_file}")
            
            # Teile große Dateien auf wenn nötig
            return self._split_citygml_if_needed(output_file)
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Fehler beim Download der Gebäudedaten: {e}")
            # Erstelle leere Platzhalter-Datei
            return self._create_empty_citygml(output_file)
    
    def _split_citygml_if_needed(self, citygml_file: Path) -> List[Path]:
        """Teilt große CityGML-Dateien in kleinere Chunks auf"""
        file_size = citygml_file.stat().st_size
        
        # Wenn Datei kleiner als 50MB, nicht aufteilen
        if file_size < 50 * 1024 * 1024:
            return [citygml_file]
        
        self.logger.info(f"Teile große CityGML-Datei auf ({file_size / 1024 / 1024:.1f} MB)...")
        
        # Hier würde die Aufteilungslogik implementiert werden
        # Für jetzt geben wir nur die Original-Datei zurück
        return [citygml_file]
    
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
        from pyproj import Transformer
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