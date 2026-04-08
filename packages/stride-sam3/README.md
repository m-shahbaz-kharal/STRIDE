# liguard-sam3

SAM3 (Segment Anything Model 3) integration for LiGuard-Web.

## Installation

```bash
pip install liguard-sam3
```

For server functionality (to run the SAM3 API server):

```bash
pip install liguard-sam3[server]
```

## Nodes

| Node | Description |
|------|-------------|
| `sam3.connect` | Connect to SAM3 server |
| `sam3.disconnect` | Close connection |
| `sam3.heartbeat` | Keep session alive |
| `sam3.set_image` | Set image for segmentation |
| `sam3.prompt_text` | Add text prompt |
| `sam3.prompt_box` | Add box prompt |
| `sam3.prompt_point` | Add point prompt |
| `sam3.get_results` | Get segmentation results |
| `sam3.visualize` | Get annotated image |
| `sam3.reset` | Clear prompts |
| `sam3.segment_image` | One-shot segmentation |

## Running the Server

```bash
python -m liguard_sam3.server --host 0.0.0.0 --port 8765
```

Requires SAM3 model installed in the environment.
