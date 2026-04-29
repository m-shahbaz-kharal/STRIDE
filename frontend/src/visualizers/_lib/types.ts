/**
 * Wire-payload types observed by the visualizers.
 *
 * Payload shapes are emitted by stride-core and contributing packages — see
 * `packages/stride-core/src/stride_core/typesystem.py` and the various
 * `_type` literals in `packages/stride-{package}/nodes.py`. Frontend
 * visualizers decode these once on input.
 */

export interface PointCloudPayload {
  _type: "PointCloud";
  num_points: number;
  positions_b64?: string;
  fields_b64?: Record<string, string>;
  positions?: number[][];
  fields?: Record<string, number[]>;
  frame?: string | null;
  metadata?: Record<string, unknown>;
}

export interface BBox3DPayload {
  _type?: string;
  id?: number | null;
  center: number[]; // [x, y, z]
  size: number[]; // [w, h, d]
  rotation?: number[] | null;
  velocity?: number[] | null;
  confidence?: number | null;
  class_id?: number | null;
  class_name?: string | null;
  frame?: string | null;
}

export interface Track3DPayload extends BBox3DPayload {
  _type?: string;
  id: number;
  track_age?: number;
  track_score?: number;
  /** Optional history of recent centers for trail rendering. */
  history?: number[][];
}

export interface Region3DPayload {
  _type?: string;
  name: string;
  center: number[];
  size: number[];
  rotation?: number[] | null;
}

export interface Detections3DPayload {
  _type: "Detections3D";
  detector?: string;
  boxes: BBox3DPayload[];
  scene_metadata?: Record<string, unknown> | null;
}

export interface Scene3DPayload {
  _type: "Scene3D";
  point_cloud: PointCloudPayload;
  boxes: BBox3DPayload[];
  regions: Region3DPayload[];
  occupancy?: number[];
  image_overlays?: string[];
}

// ===========================================================================
// 2-D types
// ===========================================================================

export interface BBox2DPayload {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  confidence: number;
  class_id: number;
  class_name: string;
  track_id?: number | null;
}

export interface Detections2DPayload {
  _type: "Detections2D";
  image_width: number;
  image_height: number;
  boxes: BBox2DPayload[];
  image?: string | null;
}

export interface KeypointInstance {
  bbox?: BBox2DPayload;
  /** Each keypoint is ``[x, y, visibility?]``. */
  keypoints: number[][];
}

export interface KeypointsPayload {
  _type: "Keypoints";
  schema?: string;
  schema_name?: string | null;
  instances: KeypointInstance[];
  /** Optional skeleton edge list (pairs of keypoint indices). */
  skeleton?: number[][];
}

export interface MaskPayload {
  _type: "Mask";
  width: number;
  height: number;
  data_b64: string;
  encoding?: string;
}

export interface DepthMapPayload {
  _type: "DepthMap";
  width: number;
  height: number;
  depth_b64: string;
  min_depth?: number;
  max_depth?: number;
  /** Optional pre-rendered visualization (data URL). */
  image?: string | null;
}

// ===========================================================================
// COCO-17 default skeleton (used by YOLO-pose and most pose models).
// 0=nose 1=l_eye 2=r_eye 3=l_ear 4=r_ear 5=l_sho 6=r_sho 7=l_elb 8=r_elb
// 9=l_wri 10=r_wri 11=l_hip 12=r_hip 13=l_knee 14=r_knee 15=l_ank 16=r_ank
// ===========================================================================
export const COCO17_SKELETON: number[][] = [
  [5, 7], [7, 9],     // left arm
  [6, 8], [8, 10],    // right arm
  [11, 13], [13, 15], // left leg
  [12, 14], [14, 16], // right leg
  [5, 6], [11, 12],   // shoulders, hips
  [5, 11], [6, 12],   // torso sides
  [0, 1], [0, 2],     // nose-eyes
  [1, 3], [2, 4],     // eyes-ears
];

/** Type-narrowing helper. */
export function isPointCloud(v: unknown): v is PointCloudPayload {
  return !!v && typeof v === "object" && (v as { _type?: string })._type === "PointCloud";
}
export function isScene3D(v: unknown): v is Scene3DPayload {
  return !!v && typeof v === "object" && (v as { _type?: string })._type === "Scene3D";
}
export function isDetections3D(v: unknown): v is Detections3DPayload {
  return !!v && typeof v === "object" && (v as { _type?: string })._type === "Detections3D";
}
export function isDetections2D(v: unknown): v is Detections2DPayload {
  return !!v && typeof v === "object" && (v as { _type?: string })._type === "Detections2D";
}
export function isKeypoints(v: unknown): v is KeypointsPayload {
  return !!v && typeof v === "object" && (v as { _type?: string })._type === "Keypoints";
}
export function isMask(v: unknown): v is MaskPayload {
  return !!v && typeof v === "object" && (v as { _type?: string })._type === "Mask";
}
export function isDepthMap(v: unknown): v is DepthMapPayload {
  return !!v && typeof v === "object" && (v as { _type?: string })._type === "DepthMap";
}
export function isBBox3D(v: unknown): v is BBox3DPayload {
  return (
    !!v &&
    typeof v === "object" &&
    Array.isArray((v as BBox3DPayload).center) &&
    Array.isArray((v as BBox3DPayload).size)
  );
}
export function isRegion3D(v: unknown): v is Region3DPayload {
  return (
    !!v &&
    typeof v === "object" &&
    typeof (v as Region3DPayload).name === "string" &&
    Array.isArray((v as Region3DPayload).center) &&
    Array.isArray((v as Region3DPayload).size)
  );
}
export function isTrack3D(v: unknown): v is Track3DPayload {
  return (
    isBBox3D(v) &&
    typeof (v as Track3DPayload).id === "number" &&
    ((v as Track3DPayload).track_age !== undefined ||
      (v as Track3DPayload).track_score !== undefined ||
      (v as { _type?: string })._type === "Track3D")
  );
}
export function isImageString(v: unknown): v is string {
  return typeof v === "string" && (v.startsWith("data:image") || v.startsWith("http"));
}
