"""
Mesh Finalizer Modul
Vereinigt alle Meshes, erstellt Fundament und validiert das finale Modell
"""

import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import numpy as np
import trimesh
from trimesh.boolean import union
import pymeshlab


class MeshFinalizer:
    """Finalisiert und validiert 3D-Modelle für wasserdichte Ausgabe"""
    
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.output_dir = self.work_dir / "final"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
    
    def create_foundation(self, bbox: Tuple[float, float, float, float],
                        depth: float,
                        terrain_mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Erstellt ein Fundament (Sockel) unter dem Terrain
        
        Args:
            bbox: Bounding Box (min_x, min_y, max_x, max_y)
            depth: Tiefe des Fundaments
            terrain_mesh: Terrain-Mesh zur Bestimmung der minimalen Höhe
        
        Returns:
            Trimesh-Objekt des Fundaments
        """
        self.logger.info(f"Erstelle Fundament mit Tiefe {depth}m")
        
        # Bestimme minimale Höhe des Terrains
        min_z = np.min(terrain_mesh.vertices[:, 2])
        
        # Fundament-Dimensionen
        min_x, min_y, max_x, max_y = bbox
        bottom_z = min_z - depth
        
        # Erstelle Box-Mesh für Fundament
        foundation = trimesh.creation.box(
            extents=[max_x - min_x, max_y - min_y, depth]
        )
        
        # Positioniere Fundament
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        center_z = min_z - depth / 2
        
        foundation.apply_translation([center_x, center_y, center_z])
        
        self.logger.info(f"Fundament erstellt: {len(foundation.vertices)} Vertices, {len(foundation.faces)} Faces")
        
        return foundation
    
    def merge_meshes(self, meshes: Dict[str, trimesh.Trimesh]) -> trimesh.Trimesh:
        """
        Vereinigt mehrere Meshes zu einem einzigen wasserdichten Mesh
        
        Args:
            meshes: Dictionary mit Mesh-Namen und Trimesh-Objekten
        
        Returns:
            Vereinigtes Trimesh-Objekt
        """
        self.logger.info("Vereinige alle Meshes...")
        
        # Filtere leere Meshes
        valid_meshes = []
        for name, mesh in meshes.items():
            if mesh and len(mesh.vertices) > 0:
                valid_meshes.append(mesh)
                self.logger.debug(f"  {name}: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
            else:
                self.logger.debug(f"  {name}: leer, übersprungen")
        
        if not valid_meshes:
            self.logger.warning("Keine gültigen Meshes zum Vereinigen")
            return trimesh.Trimesh()
        
        # Vereinige Meshes
        if len(valid_meshes) == 1:
            merged = valid_meshes[0]
        else:
            # Verwende trimesh.util.concatenate für schnelle Vereinigung
            merged = trimesh.util.concatenate(valid_meshes)
            
            # Optional: Boolean Union für wasserdichtes Ergebnis
            # Dies kann sehr langsam sein für große Meshes
            if len(merged.vertices) < 50000:  # Nur für kleinere Meshes
                try:
                    self.logger.info("Führe Boolean Union durch...")
                    merged = self._boolean_union_meshes(valid_meshes)
                except Exception as e:
                    self.logger.warning(f"Boolean Union fehlgeschlagen: {e}, verwende einfache Konkatenation")
        
        # Bereinige das Mesh
        merged.remove_degenerate_faces()
        merged.remove_duplicate_faces()
        merged.remove_unreferenced_vertices()
        merged.merge_vertices()
        
        self.logger.info(f"Meshes vereinigt: {len(merged.vertices)} Vertices, {len(merged.faces)} Faces")
        
        return merged
    
    def _boolean_union_meshes(self, meshes: List[trimesh.Trimesh]) -> trimesh.Trimesh:
        """
        Führt Boolean Union auf mehreren Meshes durch
        
        Args:
            meshes: Liste von Trimesh-Objekten
        
        Returns:
            Vereinigtes Mesh
        """
        result = meshes[0]
        
        for i, mesh in enumerate(meshes[1:], 1):
            try:
                result = union([result, mesh], engine='scad')
            except Exception as e:
                self.logger.warning(f"Boolean Union für Mesh {i} fehlgeschlagen: {e}")
                # Fallback zu einfacher Konkatenation
                result = trimesh.util.concatenate([result, mesh])
        
        return result
    
    def validate_and_repair(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Validiert und repariert ein Mesh für Wasserdichtigkeit
        
        Args:
            mesh: Zu validierendes Mesh
        
        Returns:
            Repariertes Mesh
        """
        self.logger.info("Validiere und repariere Mesh...")
        
        # Basis-Validierung
        is_valid = mesh.is_valid
        is_watertight = mesh.is_watertight
        is_winding_consistent = mesh.is_winding_consistent
        
        self.logger.info(f"  Gültig: {is_valid}")
        self.logger.info(f"  Wasserdicht: {is_watertight}")
        self.logger.info(f"  Konsistente Orientierung: {is_winding_consistent}")
        
        if is_valid and is_watertight:
            self.logger.info("Mesh ist bereits wasserdicht")
            return mesh
        
        # Reparatur-Schritte
        repaired = mesh.copy()
        
        # 1. Fixiere Normalen
        if not is_winding_consistent:
            self.logger.info("Fixiere Normalen-Orientierung...")
            repaired.fix_normals()
        
        # 2. Fülle Löcher
        if not is_watertight:
            self.logger.info("Fülle Löcher...")
            repaired = self._fill_holes(repaired)
        
        # 3. Entferne selbst-schneidende Faces
        self.logger.info("Entferne selbst-schneidende Faces...")
        repaired = self._remove_self_intersections(repaired)
        
        # 4. Vereinfache wenn zu komplex
        if len(repaired.faces) > 500000:
            self.logger.info(f"Vereinfache Mesh von {len(repaired.faces)} auf 500000 Faces...")
            repaired = repaired.simplify_quadric_decimation(500000)
        
        # 5. Finale Bereinigung
        repaired.remove_degenerate_faces()
        repaired.remove_duplicate_faces()
        repaired.remove_unreferenced_vertices()
        
        # Finale Validierung
        is_valid = repaired.is_valid
        is_watertight = repaired.is_watertight
        
        self.logger.info(f"Nach Reparatur - Gültig: {is_valid}, Wasserdicht: {is_watertight}")
        
        return repaired
    
    def _fill_holes(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Füllt Löcher im Mesh
        
        Args:
            mesh: Mesh mit Löchern
        
        Returns:
            Mesh mit gefüllten Löchern
        """
        try:
            # Verwende trimesh's eingebaute Loch-Füllung
            mesh.fill_holes()
            return mesh
        except Exception as e:
            self.logger.warning(f"Loch-Füllung fehlgeschlagen: {e}")
            
            # Alternative: Verwende PyMeshLab wenn verfügbar
            try:
                return self._fill_holes_pymeshlab(mesh)
            except:
                return mesh
    
    def _fill_holes_pymeshlab(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Füllt Löcher mit PyMeshLab
        
        Args:
            mesh: Mesh mit Löchern
        
        Returns:
            Repariertes Mesh
        """
        # Erstelle MeshSet
        ms = pymeshlab.MeshSet()
        
        # Konvertiere trimesh zu pymeshlab
        vertices = mesh.vertices
        faces = mesh.faces
        
        # Erstelle Mesh in PyMeshLab
        m = pymeshlab.Mesh(vertices, faces)
        ms.add_mesh(m)
        
        # Fülle Löcher
        ms.meshing_close_holes(maxholesize=100)
        
        # Konvertiere zurück zu trimesh
        current_mesh = ms.current_mesh()
        vertices = current_mesh.vertex_matrix()
        faces = current_mesh.face_matrix()
        
        return trimesh.Trimesh(vertices=vertices, faces=faces)
    
    def _remove_self_intersections(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Entfernt selbst-schneidende Faces
        
        Args:
            mesh: Mesh mit möglichen Selbst-Schneidungen
        
        Returns:
            Bereinigtes Mesh
        """
        try:
            # Trimesh hat keine eingebaute Funktion dafür
            # Verwende PyMeshLab wenn verfügbar
            return self._remove_self_intersections_pymeshlab(mesh)
        except Exception as e:
            self.logger.warning(f"Konnte Selbst-Schneidungen nicht entfernen: {e}")
            return mesh
    
    def _remove_self_intersections_pymeshlab(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Entfernt Selbst-Schneidungen mit PyMeshLab
        
        Args:
            mesh: Mesh
        
        Returns:
            Bereinigtes Mesh
        """
        ms = pymeshlab.MeshSet()
        
        # Konvertiere zu PyMeshLab
        m = pymeshlab.Mesh(mesh.vertices, mesh.faces)
        ms.add_mesh(m)
        
        # Entferne Selbst-Schneidungen
        ms.meshing_remove_t_vertices()
        ms.meshing_repair_non_manifold_edges()
        ms.meshing_repair_non_manifold_vertices()
        
        # Konvertiere zurück
        current_mesh = ms.current_mesh()
        vertices = current_mesh.vertex_matrix()
        faces = current_mesh.face_matrix()
        
        return trimesh.Trimesh(vertices=vertices, faces=faces)
    
    def export_obj(self, mesh: trimesh.Trimesh, output_path: Path):
        """
        Exportiert Mesh als OBJ-Datei
        
        Args:
            mesh: Zu exportierendes Mesh
            output_path: Ausgabepfad
        """
        self.logger.info(f"Exportiere Mesh nach {output_path}")
        
        # Stelle sicher dass Ausgabeverzeichnis existiert
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Exportiere als OBJ
        mesh.export(output_path)
        
        # Erstelle auch MTL-Datei für Material
        mtl_path = output_path.with_suffix('.mtl')
        self._create_mtl_file(mtl_path)
        
        self.logger.info(f"Export abgeschlossen: {output_path}")
    
    def _create_mtl_file(self, mtl_path: Path):
        """
        Erstellt eine einfache MTL-Datei für das OBJ
        
        Args:
            mtl_path: Pfad zur MTL-Datei
        """
        mtl_content = """# Material file
newmtl default
Ka 0.2 0.2 0.2
Kd 0.8 0.8 0.8
Ks 0.0 0.0 0.0
Ns 10.0
d 1.0
illum 2
"""
        
        with open(mtl_path, 'w') as f:
            f.write(mtl_content)
    
    def get_mesh_statistics(self, mesh: trimesh.Trimesh) -> Dict:
        """
        Berechnet Statistiken für ein Mesh
        
        Args:
            mesh: Mesh-Objekt
        
        Returns:
            Dictionary mit Statistiken
        """
        stats = {
            'vertices': len(mesh.vertices),
            'faces': len(mesh.faces),
            'edges': len(mesh.edges),
            'is_watertight': mesh.is_watertight,
            'is_valid': mesh.is_valid,
            'is_winding_consistent': mesh.is_winding_consistent,
            'volume': float(mesh.volume) if mesh.is_watertight else None,
            'surface_area': float(mesh.area),
            'bbox': mesh.bounds.tolist() if mesh.bounds is not None else None,
            'extents': mesh.extents.tolist() if mesh.extents is not None else None
        }
        
        return stats
    
    def create_preview(self, mesh: trimesh.Trimesh, output_path: Path):
        """
        Erstellt eine Vorschau des Meshes
        
        Args:
            mesh: Mesh-Objekt
            output_path: Pfad für Vorschaubild
        """
        try:
            # Erstelle Scene
            scene = trimesh.Scene(mesh)
            
            # Rendere Vorschau
            png = scene.save_image(resolution=[1920, 1080])
            
            # Speichere Bild
            with open(output_path, 'wb') as f:
                f.write(png)
            
            self.logger.info(f"Vorschau erstellt: {output_path}")
            
        except Exception as e:
            self.logger.warning(f"Konnte keine Vorschau erstellen: {e}")