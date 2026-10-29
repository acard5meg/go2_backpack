# Go2 Front Camera Feed

## Package Structure

```
my_ros2_ws/src/go2_camera/
├── go2_camera/
│   ├── __init__.py
│   └── camera_node.py   # Main navigation code
├── launch/
│   └── camera_feed.launch.py # Launch file
├── resource/
│   └── go2_camera              # Marker file for package discovery
├── package.xml
├── setup.py
└── setup.cfg
```

## Dependencies

- ROS2 Humble (`cv_bridge`)
- Python 3, OpenCV built with GStreamer
- GStreamer H264 decoder: `nvv4l2decoder` (Jetson) or `avdec_h264` (gstreamer1.0-libav)

## How it works

The Go2 multicasts its front camera as H264 over RTP to `230.1.1.1:1720` on its wired
network. The node joins that group on the given interface, decodes it with GStreamer
(through OpenCV) in a capture thread, and publishes each frame. Each topic is only
converted and published while it has subscribers.

## Usage

1. Launch the camera node:
   ```bash
   ros2 launch go2_camera camera_feed.launch.py
   # options: multicast_iface:=<eth iface wired to the Go2> decoder:=hw|sw
   ```

### Published Topics
- `/go2_video_frames` ([sensor_msgs/Image](https://docs.ros2.org/latest/api/sensor_msgs/msg/Image.html)) - 1280x720 `bgr8`
- `/go2_video_frames/compressed` ([sensor_msgs/CompressedImage](https://docs.ros2.org/latest/api/sensor_msgs/msg/CompressedImage.html)) - JPEG, use this over Wi-Fi

In RViz, add an Image display with the topic `/go2_video_frames/compressed`
(needs `ros-humble-image-transport-plugins`).

### Parameters
| Name | Default | |
|---|---|---|
| `multicast_iface` | `enP8p1s0` | Interface wired to the Go2 |
| `decoder` | `hw` | `hw` = Jetson `nvv4l2decoder`, `sw` = `avdec_h264` on the CPU |
| `multicast_address` | `230.1.1.1` | |
| `port` | `1720` | |
| `frame_id` | `Head_upper` | Header frame of the images |
| `jpeg_quality` | `80` | |

### Generate Nodes
- `/camera_node`
