"""
Vector Extruder Modul
Extrudiert Vektordaten (Straßen, Gewässer, Vegetation) und drapiert sie auf Terrain
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional, Union
import numpy as np
import trimesh
import geopandas as gpd
from shapely.geometry import LineString, Polygon, MultiLineString, MultiPolygon, Point
from shapely.ops import unary_union
from scipy.spatial import cKDTree


class VectorExtruder:
    """Extrudiert und drapiert Vektordaten auf 3D-Terrain"""
    
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.output_dir = self.work_dir / "extruded"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
    
    def extrude_roads(self, roads_file: Path, 
                     terrain_mesh: trimesh.Trimesh,
                     thickness: float = 0.2,
                     width: float = 5.0,
                     z_offset: float = 0.1) -> trimesh.Trimesh:
        """
        Extrudiert Straßen zu 3D-Körpern auf dem Terrain
        
        Args:
            roads_file: Pfad zur GeoJSON-Datei mit Straßen
            terrain_mesh: Terrain-Mesh für Höhenbestimmung
            thickness: Dicke der Straßen in Metern
            width: Standard-Breite der Straßen in Metern
            z_offset: Höhen-Offset über dem Terrain
        
        Returns:
            Trimesh-Objekt mit extrudierten Straßen
        """
        self.logger.info(f"Extrudiere Straßen aus {roads_file}")
        
        # Lade Straßendaten
        gdf = gpd.read_file(roads_file)
        
        if gdf.empty:
            self.logger.warning("Keine Straßen gefunden")
            return trimesh.Trimesh()
        
        all_road_meshes = []
        
        # Erstelle KDTree für effiziente Höhenabfragen
        kdtree = cKDTree(terrain_mesh.vertices[:, :2])
        
        for idx, row in gdf.iterrows():
            geometry = row.geometry
            
            if isinstance(geometry, (LineString, MultiLineString)):
                # Bestimme Straßenbreite aus Attributen falls vorhanden
                road_width = self._get_road_width(row, default=width)
                
                # Konvertiere zu Liste von LineStrings
                if isinstance(geometry, LineString):
                    lines = [geometry]
                else:
                    lines = list(geometry.geoms)
                
                for line in lines:
                    # Erstelle Straßen-Mesh
                    road_mesh = self._extrude_line_to_road(
                        line, 
                        terrain_mesh, 
                        kdtree,
                        road_width, 
                        thickness, 
                        z_offset
                    )
                    
                    if road_mesh:
                        all_road_meshes.append(road_mesh)
        
        # Kombiniere alle Straßen-Meshes
        if all_road_meshes:
            combined_mesh = trimesh.util.concatenate(all_road_meshes)
            
            self.logger.info(f"Straßen-Mesh erstellt: {len(combined_mesh.vertices)} Vertices, {len(combined_mesh.faces)} Faces")
            
            # Speichere als OBJ
            output_file = self.output_dir / "roads.obj"
            combined_mesh.export(output_file)
            
            return combined_mesh
        else:
            return trimesh.Trimesh()
    
    def _extrude_line_to_road(self, line: LineString, 
                             terrain_mesh: trimesh.Trimesh,
                             kdtree: cKDTree,
                             width: float,
                             thickness: float,
                             z_offset: float) -> Optional[trimesh.Trimesh]:
        """
        Extrudiert eine einzelne Linie zu einem 3D-Straßenkörper
        
        Args:
            line: LineString-Geometrie
            terrain_mesh: Terrain-Mesh
            kdtree: KDTree für Höhenabfragen
            width: Breite der Straße
            thickness: Dicke der Straße
            z_offset: Höhen-Offset
        
        Returns:
            Trimesh-Objekt oder None
        """
        # Sample Punkte entlang der Linie
        coords = np.array(line.coords)
        
        if len(coords) < 2:
            return None
        
        # Erstelle Straßenquerschnitt (Buffer um Linie)
        buffered = line.buffer(width / 2, cap_style=2, join_style=2)
        
        if not isinstance(buffered, Polygon):
            return None
        
        # Extrahiere Außenring
        exterior_coords = np.array(buffered.exterior.coords)
        
        # Finde Höhen für alle Punkte
        heights = self._get_terrain_heights(exterior_coords[:, :2], terrain_mesh, kdtree)
        
        # Erstelle obere und untere Vertices
        top_vertices = np.column_stack([exterior_coords[:, :2], heights + z_offset])
        bottom_vertices = np.column_stack([exterior_coords[:, :2], heights + z_offset - thickness])
        
        # Kombiniere Vertices
        vertices = np.vstack([top_vertices, bottom_vertices])
        
        # Erstelle Faces
        faces = []
        n_points = len(top_vertices)
        
        # Top Face (Trianguliere Polygon)
        from scipy.spatial import Delaunay
        tri = Delaunay(exterior_coords[:, :2])
        top_faces = tri.simplices
        faces.extend(top_faces)
        
        # Bottom Face (umgekehrte Orientierung)
        bottom_faces = top_faces + n_points
        bottom_faces = bottom_faces[:, ::-1]  # Reverse winding
        faces.extend(bottom_faces)
        
        # Seitenwände
        for i in range(n_points - 1):
            # Vier Vertices für Quad
            v0 = i
            v1 = i + 1
            v2 = i + n_points
            v3 = i + 1 + n_points
            
            # Zwei Dreiecke pro Quad
            faces.append([v0, v1, v2])
            faces.append([v1, v3, v2])
        
        faces = np.array(faces)
        
        # Erstelle Mesh
        try:
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
            mesh.remove_degenerate_faces()
            return mesh
        except Exception as e:
            self.logger.warning(f"Fehler beim Erstellen des Straßen-Mesh: {e}")
            return None
    
    def drape_surface(self, surface_file: Path,
                     terrain_mesh: trimesh.Trimesh,
                     z_offset: float = 0.05,
                     thickness: Optional[float] = None) -> trimesh.Trimesh:
        """
        Drapiert Flächen (Gewässer, Vegetation) auf das Terrain
        
        Args:
            surface_file: Pfad zur GeoJSON-Datei
            terrain_mesh: Terrain-Mesh
            z_offset: Höhen-Offset über dem Terrain
            thickness: Optionale Dicke für Extrusion
        
        Returns:
            Trimesh-Objekt mit drapierten Flächen
        """
        self.logger.info(f"Drapiere Flächen aus {surface_file}")
        
        # Lade Flächendaten
        gdf = gpd.read_file(surface_file)
        
        if gdf.empty:
            self.logger.warning("Keine Flächen gefunden")
            return trimesh.Trimesh()
        
        all_surface_meshes = []
        
        # Erstelle KDTree für effiziente Höhenabfragen
        kdtree = cKDTree(terrain_mesh.vertices[:, :2])
        
        for idx, row in gdf.iterrows():
            geometry = row.geometry
            
            if isinstance(geometry, (Polygon, MultiPolygon)):
                # Konvertiere zu Liste von Polygonen
                if isinstance(geometry, Polygon):
                    polygons = [geometry]
                else:
                    polygons = list(geometry.geoms)
                
                for polygon in polygons:
                    # Erstelle Flächen-Mesh
                    surface_mesh = self._drape_polygon(
                        polygon,
                        terrain_mesh,
                        kdtree,
                        z_offset,
                        thickness
                    )
                    
                    if surface_mesh:
                        all_surface_meshes.append(surface_mesh)
        
        # Kombiniere alle Flächen-Meshes
        if all_surface_meshes:
            combined_mesh = trimesh.util.concatenate(all_surface_meshes)
            
            self.logger.info(f"Flächen-Mesh erstellt: {len(combined_mesh.vertices)} Vertices, {len(combined_mesh.faces)} Faces")
            
            return combined_mesh
        else:
            return trimesh.Trimesh()
    
    def _drape_polygon(self, polygon: Polygon,
                      terrain_mesh: trimesh.Trimesh,
                      kdtree: cKDTree,
                      z_offset: float,
                      thickness: Optional[float] = None) -> Optional[trimesh.Trimesh]:
        """
        Drapiert ein einzelnes Polygon auf das Terrain
        
        Args:
            polygon: Polygon-Geometrie
            terrain_mesh: Terrain-Mesh
            kdtree: KDTree für Höhenabfragen
            z_offset: Höhen-Offset
            thickness: Optionale Dicke
        
        Returns:
            Trimesh-Objekt oder None
        """
        # Extrahiere Koordinaten
        exterior_coords = np.array(polygon.exterior.coords)
        
        # Finde Höhen für alle Punkte
        heights = self._get_terrain_heights(exterior_coords[:, :2], terrain_mesh, kdtree)
        
        # Erstelle 3D-Vertices
        vertices = np.column_stack([exterior_coords[:, :2], heights + z_offset])
        
        # Trianguliere das Polygon
        from scipy.spatial import Delaunay
        
        # Für Triangulation verwende 2D-Koordinaten
        points_2d = exterior_coords[:, :2]
        
        # Füge innere Punkte für bessere Triangulation hinzu
        interior_points = self._generate_interior_points(polygon, spacing=5.0)
        if len(interior_points) > 0:
            interior_heights = self._get_terrain_heights(interior_points, terrain_mesh, kdtree)
            interior_3d = np.column_stack([interior_points, interior_heights + z_offset])
            
            # Kombiniere äußere und innere Punkte
            all_points_2d = np.vstack([points_2d, interior_points])
            vertices = np.vstack([vertices, interior_3d])
        else:
            all_points_2d = points_2d
        
        try:
            # Trianguliere
            tri = Delaunay(all_points_2d)
            faces = tri.simplices
            
            # Erstelle Mesh
            if thickness and thickness > 0:
                # Mit Dicke: erstelle extrudiertes Mesh
                mesh = self._create_extruded_mesh(vertices, faces, thickness)
            else:
                # Ohne Dicke: nur obere Fläche
                mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
            
            mesh.remove_degenerate_faces()
            return mesh
            
        except Exception as e:
            self.logger.warning(f"Fehler beim Drapieren des Polygons: {e}")
            return None
    
    def _create_extruded_mesh(self, top_vertices: np.ndarray, 
                            top_faces: np.ndarray, 
                            thickness: float) -> trimesh.Trimesh:
        """
        Erstellt ein extrudiertes Mesh mit Dicke
        
        Args:
            top_vertices: Obere Vertices
            top_faces: Obere Faces
            thickness: Dicke der Extrusion
        
        Returns:
            Extrudiertes Trimesh-Objekt
        """
        # Erstelle untere Vertices
        bottom_vertices = top_vertices.copy()
        bottom_vertices[:, 2] -= thickness
        
        # Kombiniere Vertices
        vertices = np.vstack([top_vertices, bottom_vertices])
        
        n_vertices = len(top_vertices)
        
        # Erstelle Faces
        faces = []
        
        # Obere Faces
        faces.extend(top_faces)
        
        # Untere Faces (umgekehrte Orientierung)
        bottom_faces = top_faces + n_vertices
        bottom_faces = bottom_faces[:, ::-1]
        faces.extend(bottom_faces)
        
        # Seitenwände (nur für äußere Kanten)
        # Dies ist vereinfacht - für korrekte Seitenwände müsste man die Randkanten identifizieren
        
        faces = np.array(faces)
        
        return trimesh.Trimesh(vertices=vertices, faces=faces)
    
    def _get_terrain_heights(self, points: np.ndarray, 
                           terrain_mesh: trimesh.Trimesh,
                           kdtree: cKDTree) -> np.ndarray:
        """
        Bestimmt Terrain-Höhen für gegebene 2D-Punkte
        
        Args:
            points: Nx2 Array mit X,Y-Koordinaten
            terrain_mesh: Terrain-Mesh
            kdtree: KDTree der Terrain-Vertices
        
        Returns:
            Array mit Höhenwerten
        """
        # Finde nächste Terrain-Vertices
        distances, indices = kdtree.query(points)
        
        # Verwende Höhen der nächsten Vertices
        heights = terrain_mesh.vertices[indices, 2]
        
        # Für genauere Ergebnisse könnte man hier Interpolation verwenden
        
        return heights
    
    def _get_road_width(self, road_row, default: float = 5.0) -> float:
        """
        Bestimmt Straßenbreite aus Attributen
        
        Args:
            road_row: GeoDataFrame-Zeile
            default: Standard-Breite
        
        Returns:
            Straßenbreite in Metern
        """
        # Prüfe verschiedene mögliche Attribute
        width_attributes = ['width', 'lanes', 'highway']
        
        if 'width' in road_row and road_row['width']:
            try:
                return float(road_row['width'])
            except:
                pass
        
        if 'lanes' in road_row and road_row['lanes']:
            try:
                lanes = int(road_row['lanes'])
                return lanes * 3.5  # 3.5m pro Spur
            except:
                pass
        
        if 'highway' in road_row:
            # Breite basierend auf Straßentyp
            highway_widths = {
                'motorway': 15.0,
                'trunk': 12.0,
                'primary': 10.0,
                'secondary': 8.0,
                'tertiary': 6.0,
                'residential': 5.0,
                'service': 3.0,
                'footway': 2.0,
                'cycleway': 2.5,
                'path': 1.5
            }
            
            highway_type = road_row['highway']
            if highway_type in highway_widths:
                return highway_widths[highway_type]
        
        return default
    
    def _generate_interior_points(self, polygon: Polygon, spacing: float = 5.0) -> np.ndarray:
        """
        Generiert innere Punkte für bessere Triangulation
        
        Args:
            polygon: Polygon-Geometrie
            spacing: Abstand zwischen Punkten
        
        Returns:
            Array mit inneren Punkten
        """
        bounds = polygon.bounds
        x_min, y_min, x_max, y_max = bounds
        
        # Erstelle Grid
        x_points = np.arange(x_min, x_max, spacing)
        y_points = np.arange(y_min, y_max, spacing)
        
        interior_points = []
        
        for x in x_points:
            for y in y_points:
                point = Point(x, y)
                if polygon.contains(point):
                    interior_points.append([x, y])
        
        return np.array(interior_points) if interior_points else np.empty((0, 2))