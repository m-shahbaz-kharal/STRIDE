# liguard-fl511

FL511 Camera integration for LiGuard-Web.

## Installation

```bash
pip install liguard-fl511
```

## Nodes

| Node | Description |
|------|-------------|
| `fl511.get_stream_url` | Get HLS URL for a camera |
| `fl511.connect` | Start streaming from a camera |
| `fl511.get_frame` | Get the next frame |
| `fl511.disconnect` | Stop streaming |

## Requirements

- FFmpeg must be installed and in PATH
- Chrome/Chromium for Selenium (optional, for URL resolution)
