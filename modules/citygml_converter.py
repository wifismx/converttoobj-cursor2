"""
CityGML zu OBJ Konverter
Extrahiert 3D-Gebäudegeometrien aus CityGML-Dateien und konvertiert sie zu OBJ
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import numpy as np
import trimesh
from pyproj import Transformer
import subprocess
import json


class CityGMLConverter:
    """Konverter für CityGML zu OBJ Format"""
    
    # CityGML Namespaces
    NAMESPACES = {
        'core': 'http://www.opengis.net/citygml/2.0',
        'bldg': 'http://www.opengis.net/citygml/building/2.0',
        'gml': 'http://www.opengis.net/gml',
        'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
    }
    
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.output_dir = self.work_dir / "buildings"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        
        # Sammle alle Vertices und Faces für das finale Mesh
        self.all_vertices = []
        self.all_faces = []
        self.vertex_offset = 0
    
    def convert_citygml_to_obj(self, citygml_files: List[Path], bbox: Optional[Tuple[float, float, float, float]] = None) -> trimesh.Trimesh:
        """
        Konvertiert CityGML-Dateien zu einem einzelnen OBJ/Trimesh-Objekt
        
        Args:
            citygml_files: Liste von CityGML-Dateien
            bbox: Optionale Bounding Box für Filterung
        
        Returns:
            Trimesh-Objekt mit allen Gebäuden
        """
        self.logger.info(f"Konvertiere {len(citygml_files)} CityGML-Dateien zu OBJ")
        
        # Reset für neue Konvertierung
        self.all_vertices = []
        self.all_faces = []
        self.vertex_offset = 0
        
        for citygml_file in citygml_files:
            try:
                self._process_citygml_file(citygml_file, bbox)
            except Exception as e:
                self.logger.error(f"Fehler bei Verarbeitung von {citygml_file}: {e}")
        
        # Erstelle finales Mesh
        if self.all_vertices and self.all_faces:
            mesh = trimesh.Trimesh(
                vertices=np.array(self.all_vertices),
                faces=np.array(self.all_faces)
            )
            
            # Bereinige das Mesh
            mesh.remove_degenerate_faces()
            mesh.remove_duplicate_faces()
            mesh.remove_unreferenced_vertices()
            
            self.logger.info(f"Gebäude-Mesh erstellt: {len(mesh.vertices)} Vertices, {len(mesh.faces)} Faces")
            
            # Speichere als OBJ
            output_file = self.output_dir / "buildings.obj"
            mesh.export(output_file)
            
            return mesh
        else:
            self.logger.warning("Keine Gebäudegeometrien gefunden, erstelle leeres Mesh")
            return trimesh.Trimesh()
    
    def _process_citygml_file(self, citygml_file: Path, bbox: Optional[Tuple[float, float, float, float]] = None):
        """
        Verarbeitet eine einzelne CityGML-Datei
        
        Args:
            citygml_file: Pfad zur CityGML-Datei
            bbox: Optionale Bounding Box für Filterung
        """
        self.logger.debug(f"Verarbeite CityGML-Datei: {citygml_file}")
        
        try:
            tree = ET.parse(citygml_file)
            root = tree.getroot()
            
            # Finde alle Building-Elemente
            buildings = root.findall('.//bldg:Building', self.NAMESPACES)
            
            for building in buildings:
                # Extrahiere Gebäude-ID wenn vorhanden
                building_id = building.get('{http://www.opengis.net/gml}id', 'unknown')
                
                # Prüfe ob Gebäude in Bounding Box liegt
                if bbox and not self._is_in_bbox(building, bbox):
                    continue
                
                # Extrahiere LOD2 Geometrien
                self._extract_lod2_geometry(building)
                
        except ET.ParseError as e:
            self.logger.error(f"XML Parse Error in {citygml_file}: {e}")
        except Exception as e:
            self.logger.error(f"Fehler bei Verarbeitung von {citygml_file}: {e}")
    
    def _extract_lod2_geometry(self, building_element):
        """
        Extrahiert LOD2 Geometrie aus einem Building-Element
        
        Args:
            building_element: XML Building-Element
        """
        # Suche nach verschiedenen LOD2 Geometrie-Typen
        geometry_types = [
            './/bldg:lod2Solid//gml:Polygon',
            './/bldg:lod2MultiSurface//gml:Polygon',
            './/bldg:lod2Geometry//gml:Polygon'
        ]
        
        polygons_found = False
        
        for geometry_path in geometry_types:
            polygons = building_element.findall(geometry_path, self.NAMESPACES)
            
            for polygon in polygons:
                vertices = self._extract_polygon_vertices(polygon)
                if vertices:
                    self._add_polygon_to_mesh(vertices)
                    polygons_found = True
        
        # Fallback zu LOD1 wenn kein LOD2 gefunden
        if not polygons_found:
            self._extract_lod1_geometry(building_element)
    
    def _extract_lod1_geometry(self, building_element):
        """
        Extrahiert LOD1 Geometrie als Fallback
        
        Args:
            building_element: XML Building-Element
        """
        geometry_types = [
            './/bldg:lod1Solid//gml:Polygon',
            './/bldg:lod1MultiSurface//gml:Polygon',
            './/bldg:lod1Geometry//gml:Polygon'
        ]
        
        for geometry_path in geometry_types:
            polygons = building_element.findall(geometry_path, self.NAMESPACES)
            
            for polygon in polygons:
                vertices = self._extract_polygon_vertices(polygon)
                if vertices:
                    self._add_polygon_to_mesh(vertices)
    
    def _extract_polygon_vertices(self, polygon_element) -> Optional[List[Tuple[float, float, float]]]:
        """
        Extrahiert Vertices aus einem Polygon-Element
        
        Args:
            polygon_element: XML Polygon-Element
        
        Returns:
            Liste von 3D-Koordinaten oder None
        """
        # Finde posList oder pos Elemente
        pos_list = polygon_element.find('.//gml:posList', self.NAMESPACES)
        
        if pos_list is not None:
            # Parse posList (space-separated coordinates)
            coords_text = pos_list.text.strip()
            coords = [float(x) for x in coords_text.split()]
            
            # Gruppiere in 3D-Punkte
            vertices = []
            for i in range(0, len(coords), 3):
                if i + 2 < len(coords):
                    vertices.append((coords[i], coords[i+1], coords[i+2]))
            
            return vertices if len(vertices) >= 3 else None
        
        # Alternative: einzelne pos Elemente
        pos_elements = polygon_element.findall('.//gml:pos', self.NAMESPACES)
        
        if pos_elements:
            vertices = []
            for pos in pos_elements:
                coords = [float(x) for x in pos.text.strip().split()]
                if len(coords) == 3:
                    vertices.append(tuple(coords))
            
            return vertices if len(vertices) >= 3 else None
        
        return None
    
    def _add_polygon_to_mesh(self, vertices: List[Tuple[float, float, float]]):
        """
        Fügt ein Polygon zum Gesamt-Mesh hinzu
        
        Args:
            vertices: Liste von 3D-Koordinaten
        """
        if len(vertices) < 3:
            return
        
        # Füge Vertices hinzu
        start_idx = len(self.all_vertices)
        self.all_vertices.extend(vertices)
        
        # Trianguliere das Polygon (einfache Fan-Triangulation)
        # Für komplexere Polygone sollte eine robustere Triangulation verwendet werden
        for i in range(1, len(vertices) - 1):
            face = [start_idx, start_idx + i, start_idx + i + 1]
            self.all_faces.append(face)
    
    def _is_in_bbox(self, building_element, bbox: Tuple[float, float, float, float]) -> bool:
        """
        Prüft ob ein Gebäude in der Bounding Box liegt
        
        Args:
            building_element: XML Building-Element
            bbox: Bounding Box (min_x, min_y, max_x, max_y)
        
        Returns:
            True wenn Gebäude in Bbox liegt
        """
        # Extrahiere boundedBy Element wenn vorhanden
        bounded_by = building_element.find('.//gml:boundedBy', self.NAMESPACES)
        
        if bounded_by is not None:
            lower_corner = bounded_by.find('.//gml:lowerCorner', self.NAMESPACES)
            upper_corner = bounded_by.find('.//gml:upperCorner', self.NAMESPACES)
            
            if lower_corner is not None and upper_corner is not None:
                lower = [float(x) for x in lower_corner.text.strip().split()]
                upper = [float(x) for x in upper_corner.text.strip().split()]
                
                # Prüfe Überschneidung
                if len(lower) >= 2 and len(upper) >= 2:
                    return not (upper[0] < bbox[0] or lower[0] > bbox[2] or
                               upper[1] < bbox[1] or lower[1] > bbox[3])
        
        # Wenn keine Bounding Box vorhanden, nehme an dass Gebäude drin ist
        return True
    
    def convert_with_external_tool(self, citygml_files: List[Path], output_file: Path) -> bool:
        """
        Verwendet externes Tool (citygml-tools) für Konvertierung falls verfügbar
        
        Args:
            citygml_files: Liste von CityGML-Dateien
            output_file: Ausgabe OBJ-Datei
        
        Returns:
            True wenn erfolgreich, False sonst
        """
        # Prüfe ob citygml-tools verfügbar ist
        try:
            result = subprocess.run(['citygml-tools', '--version'], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info("Verwende citygml-tools für Konvertierung")
                
                # Erstelle temporäre Dateiliste
                file_list = self.output_dir / "citygml_files.txt"
                with open(file_list, 'w') as f:
                    for citygml_file in citygml_files:
                        f.write(str(citygml_file.absolute()) + '\n')
                
                # Führe Konvertierung aus
                cmd = [
                    'citygml-tools',
                    'to-obj',
                    '--files-from', str(file_list),
                    '--output', str(output_file),
                    '--lod', '2'
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    self.logger.info("CityGML zu OBJ Konvertierung erfolgreich")
                    return True
                else:
                    self.logger.error(f"citygml-tools Fehler: {result.stderr}")
                    
        except FileNotFoundError:
            self.logger.debug("citygml-tools nicht gefunden, verwende eingebauten Parser")
        
        return False
    
    def create_simple_building(self, center: Tuple[float, float], 
                             width: float = 10, 
                             depth: float = 10, 
                             height: float = 15) -> trimesh.Trimesh:
        """
        Erstellt ein einfaches quaderförmiges Gebäude
        
        Args:
            center: Zentrumskoordinaten (x, y)
            width: Breite des Gebäudes
            depth: Tiefe des Gebäudes
            height: Höhe des Gebäudes
        
        Returns:
            Trimesh-Objekt des Gebäudes
        """
        # Erstelle Box-Mesh
        box = trimesh.creation.box(extents=[width, depth, height])
        
        # Verschiebe zu Position
        box.apply_translation([center[0], center[1], height/2])
        
        return box