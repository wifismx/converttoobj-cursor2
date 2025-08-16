"""
Datenverarbeitungsmodul
Handhabt Reprojektion und Clipping von Raster- und Vektordaten
"""

import logging
from pathlib import Path
from typing import Dict, Tuple, Optional, List
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.crs import CRS
import geopandas as gpd
from shapely.geometry import box, Polygon, MultiPolygon, LineString, MultiLineString, Point
from pyproj import Transformer
import json


class DataProcessor:
    """Prozessor für geografische Datenverarbeitung"""
    
    def __init__(self, work_dir: Path, target_crs: str = "EPSG:25832"):
        self.work_dir = Path(work_dir)
        self.target_crs = target_crs
        self.processed_dir = self.work_dir / "processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
    
    def process_terrain(self, terrain_file: Path, bbox: Tuple[float, float, float, float]) -> Path:
        """
        Verarbeitet Terrain-Daten: Reprojektion und Clipping
        
        Args:
            terrain_file: Pfad zur Input GeoTIFF-Datei
            bbox: Bounding Box für Clipping (min_x, min_y, max_x, max_y)
        
        Returns:
            Pfad zur verarbeiteten GeoTIFF-Datei
        """
        self.logger.info(f"Verarbeite Terrain-Datei: {terrain_file}")
        
        output_file = self.processed_dir / "terrain_processed.tif"
        
        # Erstelle Clipping-Geometrie
        clip_geom = box(*bbox)
        
        with rasterio.open(terrain_file) as src:
            # Prüfe ob Reprojektion nötig ist
            if src.crs and str(src.crs) != self.target_crs:
                self.logger.info(f"Reprojiziere von {src.crs} nach {self.target_crs}")
                
                # Berechne Transform für Ziel-CRS
                transform, width, height = calculate_default_transform(
                    src.crs, self.target_crs, src.width, src.height, *src.bounds
                )
                
                # Metadaten für Output
                kwargs = src.meta.copy()
                kwargs.update({
                    'crs': self.target_crs,
                    'transform': transform,
                    'width': width,
                    'height': height
                })
                
                # Reprojiziere und speichere temporär
                temp_file = self.processed_dir / "terrain_reprojected.tif"
                with rasterio.open(temp_file, 'w', **kwargs) as dst:
                    for i in range(1, src.count + 1):
                        reproject(
                            source=rasterio.band(src, i),
                            destination=rasterio.band(dst, i),
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=transform,
                            dst_crs=self.target_crs,
                            resampling=Resampling.bilinear
                        )
                
                # Öffne reprojizierte Datei für Clipping
                src_file = temp_file
            else:
                src_file = terrain_file
            
            # Clippe auf Bounding Box
            with rasterio.open(src_file) as src:
                # Transformiere Clipping-Geometrie wenn nötig
                if src.crs != self.target_crs:
                    transformer = Transformer.from_crs(self.target_crs, src.crs, always_xy=True)
                    coords = list(clip_geom.exterior.coords)
                    transformed_coords = [transformer.transform(x, y) for x, y in coords]
                    clip_geom = Polygon(transformed_coords)
                
                # Maske erstellen und anwenden
                out_image, out_transform = mask(src, [clip_geom], crop=True)
                
                # Update Metadaten
                out_meta = src.meta.copy()
                out_meta.update({
                    "driver": "GTiff",
                    "height": out_image.shape[1],
                    "width": out_image.shape[2],
                    "transform": out_transform,
                    "crs": self.target_crs
                })
                
                # Speichere geclipptes Terrain
                with rasterio.open(output_file, "w", **out_meta) as dest:
                    dest.write(out_image)
        
        self.logger.info(f"Terrain verarbeitet und gespeichert: {output_file}")
        
        # Lösche temporäre Datei wenn vorhanden
        temp_file = self.processed_dir / "terrain_reprojected.tif"
        if temp_file.exists():
            temp_file.unlink()
        
        return output_file
    
    def process_vectors(self, vector_files: Dict[str, Path], bbox: Tuple[float, float, float, float]) -> Dict[str, Path]:
        """
        Verarbeitet Vektordaten: Reprojektion und Clipping
        
        Args:
            vector_files: Dictionary mit Vektordateien (streets, water, vegetation)
            bbox: Bounding Box für Clipping
        
        Returns:
            Dictionary mit verarbeiteten Dateipfaden
        """
        processed_files = {}
        clip_geom = box(*bbox)
        
        for data_type, input_file in vector_files.items():
            self.logger.info(f"Verarbeite {data_type} Vektordaten: {input_file}")
            
            try:
                # Lade GeoJSON
                if input_file.suffix == '.geojson':
                    gdf = gpd.read_file(input_file)
                else:
                    # Versuche als GeoPackage oder Shapefile zu laden
                    gdf = gpd.read_file(input_file)
                
                if gdf.empty:
                    self.logger.warning(f"Keine Features in {input_file}")
                    # Erstelle leeres GeoDataFrame mit korrektem CRS
                    gdf = gpd.GeoDataFrame(geometry=[], crs=self.target_crs)
                else:
                    # Reprojiziere wenn nötig
                    if gdf.crs and str(gdf.crs) != self.target_crs:
                        self.logger.info(f"Reprojiziere {data_type} von {gdf.crs} nach {self.target_crs}")
                        gdf = gdf.to_crs(self.target_crs)
                    elif not gdf.crs:
                        # Wenn kein CRS, nehme WGS84 an (für OSM Daten)
                        self.logger.warning(f"Kein CRS gefunden für {data_type}, nehme WGS84 an")
                        gdf = gdf.set_crs("EPSG:4326")
                        gdf = gdf.to_crs(self.target_crs)
                    
                    # Clippe auf Bounding Box
                    gdf = gdf.clip(clip_geom)
                    
                    # Filtere leere Geometrien
                    gdf = gdf[~gdf.geometry.is_empty]
                
                # Speichere verarbeitete Daten
                output_file = self.processed_dir / f"{data_type}_processed.geojson"
                if not gdf.empty:
                    gdf.to_file(output_file, driver='GeoJSON')
                else:
                    # Erstelle leere GeoJSON-Datei
                    with open(output_file, 'w') as f:
                        json.dump({"type": "FeatureCollection", "features": []}, f)
                
                processed_files[data_type] = output_file
                self.logger.info(f"{data_type} verarbeitet: {output_file} ({len(gdf)} Features)")
                
            except Exception as e:
                self.logger.error(f"Fehler bei Verarbeitung von {data_type}: {e}")
                # Erstelle leere Fallback-Datei
                output_file = self.processed_dir / f"{data_type}_processed.geojson"
                with open(output_file, 'w') as f:
                    json.dump({"type": "FeatureCollection", "features": []}, f)
                processed_files[data_type] = output_file
        
        return processed_files
    
    def clip_citygml(self, citygml_files: List[Path], bbox: Tuple[float, float, float, float]) -> List[Path]:
        """
        Clippt CityGML-Dateien auf Bounding Box
        
        Args:
            citygml_files: Liste von CityGML-Dateien
            bbox: Bounding Box für Clipping
        
        Returns:
            Liste der geclippten CityGML-Dateien
        """
        clipped_files = []
        
        for citygml_file in citygml_files:
            self.logger.info(f"Clippe CityGML-Datei: {citygml_file}")
            
            # CityGML Clipping ist komplex und würde normalerweise
            # spezielle Tools wie citygml-tools erfordern
            # Für jetzt kopieren wir einfach die Dateien
            output_file = self.processed_dir / f"clipped_{citygml_file.name}"
            
            try:
                import shutil
                shutil.copy2(citygml_file, output_file)
                clipped_files.append(output_file)
                
            except Exception as e:
                self.logger.error(f"Fehler beim Clippen von {citygml_file}: {e}")
        
        return clipped_files
    
    def get_terrain_stats(self, terrain_file: Path) -> Dict:
        """
        Berechnet Statistiken für Terrain-Datei
        
        Args:
            terrain_file: Pfad zur GeoTIFF-Datei
        
        Returns:
            Dictionary mit Statistiken
        """
        stats = {}
        
        try:
            with rasterio.open(terrain_file) as src:
                data = src.read(1)
                
                # Filtere NoData-Werte
                valid_data = data[data != src.nodata] if src.nodata else data
                
                stats = {
                    'min_elevation': float(np.min(valid_data)),
                    'max_elevation': float(np.max(valid_data)),
                    'mean_elevation': float(np.mean(valid_data)),
                    'std_elevation': float(np.std(valid_data)),
                    'resolution': src.res,
                    'shape': data.shape,
                    'crs': str(src.crs),
                    'bounds': src.bounds
                }
                
        except Exception as e:
            self.logger.error(f"Fehler beim Berechnen der Terrain-Statistiken: {e}")
            stats = {
                'error': str(e)
            }
        
        return stats
    
    def merge_vector_layers(self, vector_files: Dict[str, Path], output_name: str = "merged_vectors.geojson") -> Path:
        """
        Vereinigt mehrere Vektor-Layer zu einer Datei
        
        Args:
            vector_files: Dictionary mit Vektordateien
            output_name: Name der Output-Datei
        
        Returns:
            Pfad zur vereinigten Datei
        """
        output_file = self.processed_dir / output_name
        
        all_features = []
        
        for data_type, file_path in vector_files.items():
            try:
                gdf = gpd.read_file(file_path)
                if not gdf.empty:
                    gdf['layer_type'] = data_type
                    all_features.append(gdf)
            except Exception as e:
                self.logger.warning(f"Konnte {file_path} nicht laden: {e}")
        
        if all_features:
            merged_gdf = gpd.GeoDataFrame(pd.concat(all_features, ignore_index=True))
            merged_gdf.to_file(output_file, driver='GeoJSON')
            self.logger.info(f"Vektor-Layer vereinigt: {output_file}")
        else:
            # Erstelle leere Datei
            with open(output_file, 'w') as f:
                json.dump({"type": "FeatureCollection", "features": []}, f)
        
        return output_file