# liguard-people

People detection and occupancy tracking plugin for LiGuard-Web.

## Features

- **Background subtraction**: Voxel-based background model for static scene removal
- **DBSCAN clustering**: Groups foreground points into potential person clusters
- **Human filtering**: Filters clusters by expected human dimensions
- **Simple tracking**: Hungarian algorithm-based centroid tracking across frames
- **Occupancy regions**: Define cuboid regions and count people inside
- **3D visualization**: Scene widget showing point cloud, bounding boxes, and regions

## Nodes

- `people.detect` - Detect people in point cloud, outputs list of 3D bounding boxes
- `people.create_region` - Create an occupancy region cuboid
- `people.count_occupancy` - Count people in regions
- `people.visualize` - Create Scene3D for dashboard visualization

## Algorithm

Uses classical computer vision techniques (no deep learning):
1. Voxel grid background subtraction (learns static scene over time)
2. Ground plane removal via RANSAC
3. Height-based filtering (keeps points in human height range)
4. DBSCAN clustering on remaining points
5. Cluster filtering by expected human dimensions
6. Simple IoU/centroid-based tracking for ID persistence
