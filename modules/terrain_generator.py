"""
Terrain Generator Modul
Erstellt 3D-Terrain-Meshes aus GeoTIFF Höhendaten
"""

import logging
from pathlib import Path
from typing import Tuple, Optional
import numpy as np
import rasterio
import trimesh
from scipy.interpolate import RectBivariateSpline
from scipy.spatial import Delaunay


class TerrainGenerator:
    """Generator für 3D-Terrain-Meshes aus Rasterdaten"""
    
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.output_dir = self.work_dir / "terrain"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        
        # Speichere Terrain-Daten für spätere Verwendung
        self.elevation_data = None
        self.transform = None
        self.interpolator = None
    
    def create_terrain_mesh(self, terrain_file: Path, 
                          resolution: float = 1.0,
                          simplify: bool = True,
                          max_faces: int = 100000) -> trimesh.Trimesh:
        """
        Erstellt ein 3D-Terrain-Mesh aus einer GeoTIFF-Datei
        
        Args:
            terrain_file: Pfad zur GeoTIFF-Datei
            resolution: Ziel-Auflösung in Metern (Grid-Abstand)
            simplify: Ob das Mesh vereinfacht werden soll
            max_faces: Maximale Anzahl Faces nach Vereinfachung
        
        Returns:
            Trimesh-Objekt des Terrains
        """
        self.logger.info(f"Erstelle Terrain-Mesh aus {terrain_file}")
        
        with rasterio.open(terrain_file) as src:
            # Lese Höhendaten
            elevation = src.read(1)
            self.elevation_data = elevation
            self.transform = src.transform
            
            # Berechne Koordinaten-Grid
            height, width = elevation.shape
            
            # Bestimme Sampling basierend auf gewünschter Auflösung
            pixel_size_x = abs(src.transform[0])
            pixel_size_y = abs(src.transform[4])
            
            step_x = max(1, int(resolution / pixel_size_x))
            step_y = max(1, int(resolution / pixel_size_y))
            
            # Sample das Grid
            sampled_elevation = elevation[::step_y, ::step_x]
            sampled_height, sampled_width = sampled_elevation.shape
            
            self.logger.debug(f"Terrain Grid: {sampled_width}x{sampled_height} Punkte")
            
            # Erstelle Koordinaten-Arrays
            x_coords = np.zeros((sampled_height, sampled_width))
            y_coords = np.zeros((sampled_height, sampled_width))
            z_coords = sampled_elevation
            
            for i in range(sampled_height):
                for j in range(sampled_width):
                    # Transformiere Pixel-Koordinaten zu Welt-Koordinaten
                    x, y = src.transform * (j * step_x, i * step_y)
                    x_coords[i, j] = x
                    y_coords[i, j] = y
            
            # Erstelle Interpolator für spätere Höhenabfragen
            self._create_interpolator(src)
            
            # Erstelle Mesh
            mesh = self._create_mesh_from_grid(x_coords, y_coords, z_coords)
            
            # Prüfe ob Mesh gültig ist
            if mesh is None or len(mesh.vertices) == 0 or len(mesh.faces) == 0:
                self.logger.error("Mesh-Erstellung fehlgeschlagen")
                # Erstelle ein einfaches Plane-Mesh als Fallback
                mesh = self._create_fallback_mesh(src.bounds, np.mean(elevation))
            
            if simplify and len(mesh.faces) > max_faces:
                self.logger.info(f"Vereinfache Mesh von {len(mesh.faces)} auf max {max_faces} Faces")
                try:
                    mesh = mesh.simplify_quadric_decimation(max_faces)
                except Exception as e:
                    self.logger.warning(f"Mesh-Vereinfachung fehlgeschlagen: {e}")
            
            # Bereinige das Mesh vorsichtig
            try:
                mesh.remove_degenerate_faces()
                mesh.remove_duplicate_faces()
                mesh.remove_unreferenced_vertices()
            except Exception as e:
                self.logger.warning(f"Mesh-Bereinigung fehlgeschlagen: {e}")
            
            self.logger.info(f"Terrain-Mesh erstellt: {len(mesh.vertices)} Vertices, {len(mesh.faces)} Faces")
            
            # Speichere als OBJ
            output_file = self.output_dir / "terrain.obj"
            mesh.export(output_file)
            
            return mesh
    
    def _create_mesh_from_grid(self, x_coords: np.ndarray, 
                              y_coords: np.ndarray, 
                              z_coords: np.ndarray) -> Optional[trimesh.Trimesh]:
        """
        Erstellt ein Trimesh aus Grid-Koordinaten
        
        Args:
            x_coords: 2D-Array mit X-Koordinaten
            y_coords: 2D-Array mit Y-Koordinaten
            z_coords: 2D-Array mit Z-Koordinaten (Höhen)
        
        Returns:
            Trimesh-Objekt oder None
        """
        height, width = x_coords.shape
        
        if height < 2 or width < 2:
            self.logger.error("Grid zu klein für Mesh-Erstellung")
            return None
        
        # Erstelle Vertex-Liste
        vertices = []
        for i in range(height):
            for j in range(width):
                vertices.append([x_coords[i, j], y_coords[i, j], z_coords[i, j]])
        
        vertices = np.array(vertices)
        
        # Erstelle Face-Liste (zwei Dreiecke pro Grid-Zelle)
        faces = []
        for i in range(height - 1):
            for j in range(width - 1):
                # Vertex-Indizes für diese Zelle
                v0 = i * width + j
                v1 = i * width + (j + 1)
                v2 = (i + 1) * width + j
                v3 = (i + 1) * width + (j + 1)
                
                # Zwei Dreiecke pro Zelle
                faces.append([v0, v1, v2])
                faces.append([v1, v3, v2])
        
        if len(faces) == 0:
            self.logger.error("Keine Faces erstellt")
            return None
        
        faces = np.array(faces)
        
        # Erstelle Mesh
        try:
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
            return mesh
        except Exception as e:
            self.logger.error(f"Fehler bei Mesh-Erstellung: {e}")
            return None
    
    def _create_fallback_mesh(self, bounds, mean_elevation: float) -> trimesh.Trimesh:
        """
        Erstellt ein einfaches Plane-Mesh als Fallback
        
        Args:
            bounds: Rasterio bounds object
            mean_elevation: Durchschnittliche Höhe
        
        Returns:
            Trimesh-Objekt
        """
        self.logger.warning("Erstelle Fallback-Mesh")
        
        # Erstelle ein einfaches Rechteck
        vertices = np.array([
            [bounds.left, bounds.bottom, mean_elevation],
            [bounds.right, bounds.bottom, mean_elevation],
            [bounds.right, bounds.top, mean_elevation],
            [bounds.left, bounds.top, mean_elevation]
        ])
        
        faces = np.array([
            [0, 1, 2],
            [0, 2, 3]
        ])
        
        return trimesh.Trimesh(vertices=vertices, faces=faces)
    
    def _create_interpolator(self, raster_src):
        """
        Erstellt einen Interpolator für Höhenabfragen
        
        Args:
            raster_src: Offenes rasterio Dataset
        """
        elevation = raster_src.read(1)
        height, width = elevation.shape
        
        # Erstelle Koordinaten-Arrays für Interpolation
        x = np.arange(width)
        y = np.arange(height)
        
        # Erstelle 2D-Interpolator
        self.interpolator = RectBivariateSpline(y, x, elevation, kx=1, ky=1)
    
    def get_elevation_at_point(self, x: float, y: float) -> float:
        """
        Gibt die interpolierte Höhe an einem Punkt zurück
        
        Args:
            x: X-Koordinate (Welt-Koordinaten)
            y: Y-Koordinate (Welt-Koordinaten)
        
        Returns:
            Interpolierte Höhe
        """
        if self.interpolator is None or self.transform is None:
            raise ValueError("Terrain muss zuerst mit create_terrain_mesh erstellt werden")
        
        # Transformiere Welt-Koordinaten zu Pixel-Koordinaten
        inv_transform = ~self.transform
        px, py = inv_transform * (x, y)
        
        # Interpoliere Höhe
        elevation = float(self.interpolator(py, px)[0, 0])
        
        return elevation
    
    def get_elevation_along_line(self, points: np.ndarray, num_samples: int = 100) -> np.ndarray:
        """
        Gibt interpolierte Höhen entlang einer Linie zurück
        
        Args:
            points: Array von 2D-Punkten [[x1,y1], [x2,y2], ...]
            num_samples: Anzahl der Sample-Punkte entlang der Linie
        
        Returns:
            Array mit Höhenwerten
        """
        elevations = []
        
        # Berechne Gesamtlänge
        total_length = 0
        for i in range(len(points) - 1):
            segment_length = np.linalg.norm(points[i+1] - points[i])
            total_length += segment_length
        
        # Sample entlang der Linie
        current_length = 0
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            segment_length = np.linalg.norm(p2 - p1)
            
            # Anzahl Samples für dieses Segment
            segment_samples = int(num_samples * segment_length / total_length)
            
            for t in np.linspace(0, 1, segment_samples, endpoint=(i == len(points) - 2)):
                # Interpoliere Position
                pos = p1 + t * (p2 - p1)
                
                # Hole Höhe
                elevation = self.get_elevation_at_point(pos[0], pos[1])
                elevations.append(elevation)
        
        return np.array(elevations)
    
    def create_terrain_from_points(self, points: np.ndarray, 
                                  z_values: np.ndarray) -> trimesh.Trimesh:
        """
        Erstellt ein Terrain-Mesh aus unregelmäßigen Punkten
        
        Args:
            points: Nx2 Array mit X,Y-Koordinaten
            z_values: N Array mit Höhenwerten
        
        Returns:
            Trimesh-Objekt
        """
        # Delaunay-Triangulation für unregelmäßige Punkte
        tri = Delaunay(points)
        
        # Erstelle 3D-Vertices
        vertices = np.column_stack([points, z_values])
        
        # Erstelle Mesh
        mesh = trimesh.Trimesh(vertices=vertices, faces=tri.simplices)
        
        return mesh
    
    def add_skirt(self, mesh: trimesh.Trimesh, depth: float = 10.0) -> trimesh.Trimesh:
        """
        Fügt einen "Rock" um das Terrain hinzu (vertikale Wände an den Rändern)
        
        Args:
            mesh: Terrain-Mesh
            depth: Tiefe des Rocks unter dem niedrigsten Punkt
        
        Returns:
            Mesh mit Rock
        """
        # Finde Rand-Vertices
        edges = mesh.edges_unique
        edge_points = mesh.vertices[edges]
        
        # Finde äußere Kanten (nur eine Face zugeordnet)
        edge_face_count = np.zeros(len(edges))
        for i, edge in enumerate(edges):
            faces_with_edge = np.sum(
                (mesh.faces == edge[0]).any(axis=1) & 
                (mesh.faces == edge[1]).any(axis=1)
            )
            edge_face_count[i] = faces_with_edge
        
        boundary_edges = edges[edge_face_count == 1]
        
        # Erstelle Rock-Geometrie
        skirt_vertices = []
        skirt_faces = []
        
        base_vertex_count = len(mesh.vertices)
        
        for edge in boundary_edges:
            v1, v2 = edge
            p1 = mesh.vertices[v1]
            p2 = mesh.vertices[v2]
            
            # Erstelle untere Punkte
            p1_bottom = p1.copy()
            p1_bottom[2] = p1[2] - depth
            p2_bottom = p2.copy()
            p2_bottom[2] = p2[2] - depth
            
            # Füge neue Vertices hinzu
            new_idx = base_vertex_count + len(skirt_vertices)
            skirt_vertices.extend([p1_bottom, p2_bottom])
            
            # Erstelle zwei Dreiecke für die Wand
            skirt_faces.append([v1, new_idx, v2])
            skirt_faces.append([v2, new_idx, new_idx + 1])
        
        # Kombiniere Original-Mesh mit Rock
        combined_vertices = np.vstack([mesh.vertices, skirt_vertices])
        combined_faces = np.vstack([mesh.faces, skirt_faces])
        
        return trimesh.Trimesh(vertices=combined_vertices, faces=combined_faces)