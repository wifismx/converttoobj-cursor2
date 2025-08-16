#!/usr/bin/env python3
"""
Koordinaten-Konverter für NRW 3D Generator
Konvertiert WGS84 (Länge/Breite) zu EPSG:25832 (UTM Zone 32N)
"""

import argparse
from pyproj import Transformer


def convert_bbox_to_utm(lon_min: float, lat_min: float, lon_max: float, lat_max: float) -> tuple:
    """
    Konvertiert eine Bounding Box von WGS84 zu EPSG:25832
    
    Args:
        lon_min: Minimale Länge (WGS84)
        lat_min: Minimale Breite (WGS84)
        lon_max: Maximale Länge (WGS84)
        lat_max: Maximale Breite (WGS84)
    
    Returns:
        Tuple (min_x, min_y, max_x, max_y) in EPSG:25832
    """
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    
    # Konvertiere alle vier Ecken
    min_x, min_y = transformer.transform(lon_min, lat_min)
    max_x, max_y = transformer.transform(lon_max, lat_max)
    
    # Stelle sicher dass min/max korrekt sind
    if min_x > max_x:
        min_x, max_x = max_x, min_x
    if min_y > max_y:
        min_y, max_y = max_y, min_y
    
    return (min_x, min_y, max_x, max_y)


def convert_point_to_utm(lon: float, lat: float) -> tuple:
    """
    Konvertiert einen einzelnen Punkt von WGS84 zu EPSG:25832
    
    Args:
        lon: Länge (WGS84)
        lat: Breite (WGS84)
    
    Returns:
        Tuple (x, y) in EPSG:25832
    """
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    x, y = transformer.transform(lon, lat)
    return (x, y)


def main():
    parser = argparse.ArgumentParser(
        description='Konvertiert WGS84 Koordinaten zu EPSG:25832 (UTM Zone 32N)'
    )
    
    parser.add_argument(
        'coordinates',
        type=str,
        help='Koordinaten im Format: "lon,lat" für Punkt oder "lon_min,lat_min,lon_max,lat_max" für Bounding Box'
    )
    
    parser.add_argument(
        '--expand',
        type=float,
        default=0,
        help='Erweitert die Bounding Box um X Meter in alle Richtungen (Standard: 0)'
    )
    
    args = parser.parse_args()
    
    # Parse Koordinaten
    coords = [float(x.strip()) for x in args.coordinates.split(',')]
    
    if len(coords) == 2:
        # Einzelner Punkt
        lon, lat = coords
        x, y = convert_point_to_utm(lon, lat)
        
        print(f"\nPunkt-Konvertierung:")
        print(f"WGS84: {lon:.6f}°E, {lat:.6f}°N")
        print(f"EPSG:25832: {x:.2f}, {y:.2f}")
        
        if args.expand > 0:
            # Erstelle Bounding Box um den Punkt
            min_x = x - args.expand
            min_y = y - args.expand
            max_x = x + args.expand
            max_y = y + args.expand
            
            print(f"\nBounding Box ({args.expand}m Radius):")
            print(f"EPSG:25832: {min_x:.2f},{min_y:.2f},{max_x:.2f},{max_y:.2f}")
            print(f"\nFür nrw_3d_generator.py:")
            print(f'python nrw_3d_generator.py "{min_x:.2f},{min_y:.2f},{max_x:.2f},{max_y:.2f}"')
    
    elif len(coords) == 4:
        # Bounding Box
        lon_min, lat_min, lon_max, lat_max = coords
        min_x, min_y, max_x, max_y = convert_bbox_to_utm(lon_min, lat_min, lon_max, lat_max)
        
        print(f"\nBounding Box Konvertierung:")
        print(f"WGS84: {lon_min:.6f},{lat_min:.6f},{lon_max:.6f},{lat_max:.6f}")
        print(f"EPSG:25832: {min_x:.2f},{min_y:.2f},{max_x:.2f},{max_y:.2f}")
        
        if args.expand > 0:
            min_x -= args.expand
            min_y -= args.expand
            max_x += args.expand
            max_y += args.expand
            print(f"\nErweitert um {args.expand}m:")
            print(f"EPSG:25832: {min_x:.2f},{min_y:.2f},{max_x:.2f},{max_y:.2f}")
        
        # Berechne Größe
        width = max_x - min_x
        height = max_y - min_y
        area = width * height / 1000000  # in km²
        
        print(f"\nGröße: {width:.0f}m x {height:.0f}m = {area:.2f} km²")
        print(f"\nFür nrw_3d_generator.py:")
        print(f'python nrw_3d_generator.py "{min_x:.2f},{min_y:.2f},{max_x:.2f},{max_y:.2f}"')
    
    else:
        print("Fehler: Ungültiges Koordinatenformat")
        print("Erwarte: 'lon,lat' oder 'lon_min,lat_min,lon_max,lat_max'")
        return 1
    
    # Zeige bekannte Orte in NRW
    print("\n--- Bekannte Orte in NRW (EPSG:25832) ---")
    places = {
        "Köln Dom": (356800, 5645200),
        "Düsseldorf Altstadt": (338500, 5678500),
        "Bonn Zentrum": (365000, 5620000),
        "Aachen Dom": (294000, 5630000),
        "Münster Dom": (404000, 5757000),
        "Paderborn Dom": (494000, 5728000),
        "Dortmund Zentrum": (395000, 5708000),
        "Essen Zentrum": (361000, 5706000),
        "Wuppertal Zentrum": (367000, 5682000),
        "Bielefeld Zentrum": (466000, 5765000)
    }
    
    for name, (x, y) in places.items():
        print(f"{name}: {x},{y}")


if __name__ == "__main__":
    main()