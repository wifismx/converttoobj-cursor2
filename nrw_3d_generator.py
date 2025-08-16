#!/usr/bin/env python3
"""
NRW 3D Model Generator
Generiert wasserdichte 3D-Modelle im OBJ-Format aus Geoportal NRW Daten
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Tuple, Optional
import json
from pyproj import Transformer

from modules.data_downloader import DataDownloader
from modules.data_processor import DataProcessor
from modules.citygml_converter import CityGMLConverter
from modules.terrain_generator import TerrainGenerator
from modules.vector_extruder import VectorExtruder
from modules.mesh_finalizer import MeshFinalizer


def setup_logging(verbose: bool = False):
    """Logging-Konfiguration einrichten"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
    """
    Parse Bounding Box String und konvertiere ggf. von WGS84 zu EPSG:25832
    Format: "min_x,min_y,max_x,max_y"
    """
    try:
        coords = [float(x.strip()) for x in bbox_str.split(',')]
        if len(coords) != 4:
            raise ValueError("Bounding Box muss 4 Koordinaten haben")
        
        min_x, min_y, max_x, max_y = coords
        
        # Prüfe ob Koordinaten in WGS84 sind (typisch: -180 bis 180 für Länge, -90 bis 90 für Breite)
        # NRW liegt etwa bei 6-9°E und 50-52°N
        if -180 <= min_x <= 180 and -90 <= min_y <= 90 and -180 <= max_x <= 180 and -90 <= max_y <= 90:
            # Wahrscheinlich WGS84 - konvertiere zu EPSG:25832
            logging.getLogger(__name__).warning("Koordinaten scheinen in WGS84 zu sein, konvertiere zu EPSG:25832...")
            
            transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
            
            # Konvertiere alle vier Ecken
            min_x_utm, min_y_utm = transformer.transform(min_x, min_y)
            max_x_utm, max_y_utm = transformer.transform(max_x, max_y)
            
            # Stelle sicher dass min/max korrekt sind
            if min_x_utm > max_x_utm:
                min_x_utm, max_x_utm = max_x_utm, min_x_utm
            if min_y_utm > max_y_utm:
                min_y_utm, max_y_utm = max_y_utm, min_y_utm
            
            logging.getLogger(__name__).info(f"Konvertiert zu EPSG:25832: {min_x_utm:.2f},{min_y_utm:.2f},{max_x_utm:.2f},{max_y_utm:.2f}")
            
            return (min_x_utm, min_y_utm, max_x_utm, max_y_utm)
        
        # Prüfe ob Koordinaten plausibel für EPSG:25832 sind
        # NRW liegt etwa zwischen 280000-450000 (X) und 5600000-5800000 (Y)
        if min_x < 100000 or max_x < 100000 or min_y < 1000000 or max_y < 1000000:
            logging.getLogger(__name__).warning(f"Koordinaten scheinen nicht in EPSG:25832 zu sein: {coords}")
            logging.getLogger(__name__).warning("Falls es WGS84-Koordinaten sind, verwenden Sie das Format: lon_min,lat_min,lon_max,lat_max")
        
        return (min_x, min_y, max_x, max_y)
        
    except Exception as e:
        raise ValueError(f"Ungültiges Bounding Box Format: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Generiere wasserdichte 3D-Modelle aus NRW Geoportal Daten'
    )
    
    parser.add_argument(
        'bbox',
        type=str,
        help='Bounding Box im Format: min_x,min_y,max_x,max_y (EPSG:25832 oder WGS84)'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='modell.obj',
        help='Ausgabe OBJ-Datei (Standard: modell.obj)'
    )
    
    parser.add_argument(
        '-w', '--workdir',
        type=str,
        default='./work',
        help='Arbeitsverzeichnis für temporäre Dateien (Standard: ./work)'
    )
    
    parser.add_argument(
        '--terrain-resolution',
        type=float,
        default=1.0,
        help='Auflösung des Terrain-Meshes in Metern (Standard: 1.0)'
    )
    
    parser.add_argument(
        '--road-thickness',
        type=float,
        default=0.2,
        help='Dicke der Straßen in Metern (Standard: 0.2)'
    )
    
    parser.add_argument(
        '--foundation-depth',
        type=float,
        default=10.0,
        help='Tiefe des Fundament-Sockels in Metern (Standard: 10.0)'
    )
    
    parser.add_argument(
        '--skip-download',
        action='store_true',
        help='Überspringt den Download (nutzt existierende Daten)'
    )
    
    parser.add_argument(
        '--skip-validation',
        action='store_true',
        help='Überspringt die Mesh-Validierung'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Ausführliche Ausgabe'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        help='JSON-Konfigurationsdatei (überschreibt Kommandozeilenargumente)'
    )
    
    args = parser.parse_args()
    
    # Logging einrichten
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # Konfiguration laden falls vorhanden
    config = vars(args).copy()
    if args.config:
        try:
            with open(args.config, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
                logger.info(f"Konfiguration geladen aus {args.config}")
        except Exception as e:
            logger.error(f"Fehler beim Laden der Konfiguration: {e}")
            sys.exit(1)
    
    # Bounding Box parsen (mit automatischer WGS84-Konvertierung)
    try:
        bbox = parse_bbox(config['bbox'])
        logger.info(f"Bounding Box (EPSG:25832): {bbox}")
        
        # Berechne und zeige Größe
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        area = width * height / 1000000  # in km²
        logger.info(f"Bereich: {width:.0f}m x {height:.0f}m = {area:.2f} km²")
        
        if area > 10:
            logger.warning("Großer Bereich gewählt (>10 km²) - dies kann zu Speicherproblemen führen")
            
    except ValueError as e:
        logger.error(str(e))
        logger.info("\nHinweis: Sie können WGS84-Koordinaten (Länge/Breite) verwenden:")
        logger.info("  Beispiel: python nrw_3d_generator.py \"6.95,50.94,6.96,50.95\"")
        logger.info("\nOder EPSG:25832-Koordinaten (UTM):")
        logger.info("  Beispiel: python nrw_3d_generator.py \"356800,5645200,357800,5646200\"")
        sys.exit(1)
    
    # Arbeitsverzeichnis erstellen
    work_dir = Path(config['workdir'])
    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Arbeitsverzeichnis: {work_dir.absolute()}")
    
    try:
        # Phase 1: Daten herunterladen
        if not config['skip_download']:
            logger.info("=== Phase 1: Datendownload ===")
            downloader = DataDownloader(work_dir)
            
            logger.info("Lade Geländedaten...")
            terrain_file = downloader.download_terrain(bbox)
            
            logger.info("Lade Gebäudedaten (CityGML)...")
            building_files = downloader.download_buildings(bbox)
            
            logger.info("Lade OSM-Daten (Straßen, Gewässer, Vegetation)...")
            osm_files = downloader.download_osm_data(bbox)
        else:
            logger.info("Download übersprungen - nutze existierende Daten")
            terrain_file = work_dir / "raw" / "terrain" / "gelaende.tif"
            building_files = list((work_dir / "raw" / "buildings").glob("*.gml"))
            osm_files = {
                'streets': work_dir / "raw" / "osm" / "strassen.geojson",
                'water': work_dir / "raw" / "osm" / "gewaesser.geojson",
                'vegetation': work_dir / "raw" / "osm" / "vegetation.geojson"
            }
        
        # Phase 2: Datenverarbeitung
        logger.info("=== Phase 2: Datenverarbeitung ===")
        processor = DataProcessor(work_dir, target_crs="EPSG:25832")
        
        logger.info("Reprojektion und Clipping...")
        processed_terrain = processor.process_terrain(terrain_file, bbox)
        processed_vectors = processor.process_vectors(osm_files, bbox)
        
        logger.info("Konvertiere CityGML zu OBJ...")
        converter = CityGMLConverter(work_dir)
        buildings_obj = converter.convert_citygml_to_obj(building_files, bbox)
        
        # Phase 3: 3D-Szenen-Assemblierung
        logger.info("=== Phase 3: 3D-Szenen-Assemblierung ===")
        
        logger.info("Erstelle Terrain-Mesh...")
        terrain_gen = TerrainGenerator(work_dir)
        terrain_mesh = terrain_gen.create_terrain_mesh(
            processed_terrain,
            resolution=config['terrain_resolution']
        )
        
        logger.info("Extrudiere Vektordaten...")
        extruder = VectorExtruder(work_dir)
        
        road_meshes = extruder.extrude_roads(
            processed_vectors['streets'],
            terrain_mesh,
            thickness=config['road_thickness']
        )
        
        water_mesh = extruder.drape_surface(
            processed_vectors['water'],
            terrain_mesh,
            z_offset=0.05  # Leicht über dem Terrain
        )
        
        vegetation_mesh = extruder.drape_surface(
            processed_vectors['vegetation'],
            terrain_mesh,
            z_offset=0.1
        )
        
        # Phase 4: Finalisierung
        logger.info("=== Phase 4: Finalisierung ===")
        finalizer = MeshFinalizer(work_dir)
        
        logger.info("Erstelle Fundament...")
        foundation = finalizer.create_foundation(
            bbox,
            depth=config['foundation_depth'],
            terrain_mesh=terrain_mesh
        )
        
        logger.info("Vereinige alle Meshes...")
        all_meshes = {
            'terrain': terrain_mesh,
            'foundation': foundation,
            'buildings': buildings_obj,
            'roads': road_meshes,
            'water': water_mesh,
            'vegetation': vegetation_mesh
        }
        
        unified_mesh = finalizer.merge_meshes(all_meshes)
        
        if not config['skip_validation']:
            logger.info("Validiere und repariere Geometrie...")
            final_mesh = finalizer.validate_and_repair(unified_mesh)
        else:
            logger.info("Validierung übersprungen")
            final_mesh = unified_mesh
        
        # Export
        output_path = Path(config['output'])
        logger.info(f"Exportiere finales Modell nach {output_path}...")
        finalizer.export_obj(final_mesh, output_path)
        
        logger.info(f"✓ 3D-Modell erfolgreich erstellt: {output_path.absolute()}")
        
        # Statistiken ausgeben
        stats = finalizer.get_mesh_statistics(final_mesh)
        logger.info("=== Modell-Statistiken ===")
        logger.info(f"Vertices: {stats['vertices']:,}")
        logger.info(f"Faces: {stats['faces']:,}")
        if stats['bbox']:
            logger.info(f"Bounding Box: {stats['bbox']}")
        logger.info(f"Wasserdicht: {'Ja' if stats['is_watertight'] else 'Nein'}")
        
    except Exception as e:
        logger.error(f"Fehler bei der Verarbeitung: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()