# stride-mediapipe

Google MediaPipe pose / hands / face landmark nodes for STRIDE.

This package wraps the legacy `mediapipe.solutions.{pose,hands,face_mesh}`
APIs (the most-deployed and most-stable APIs across MediaPipe versions).
All models are bundled with the `mediapipe` pip wheel — no extra
downloads are required.

## Installation

```bash
pip install mediapipe opencv-python
```

> Note: MediaPipe currently ships wheels for Python 3.9 – 3.12 on
> Windows / Linux / macOS x86_64.  On unsupported platforms or Python
> versions the package will load but the nodes will raise a clear
> error at `forward()` time.

## Nodes

| Node ID                   | Purpose                                  |
|---------------------------|------------------------------------------|
| `image.pose.mediapipe`    | 33-point body pose (BlazePose Lite/Heavy)|
| `image.hands.mediapipe`   | 21-point landmarks per hand              |
| `image.face.mediapipe`    | 468-point face mesh                      |

Each node emits a STRIDE `keypoints` record alongside an annotated image.
