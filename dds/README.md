# Go2 DDS setup (Jetson)

How the Jetson splits ROS 2 / CycloneDDS traffic between the Unitree Go2 (wired) and
everything else (Wi-Fi), and how data gets from one side to the other.

## Overview

```
 Go2 main board 192.168.123.161 ┐
 Go2 dock       192.168.123.18  ┴─ eth (enP8p1s0, 192.168.123.99)
                                        │  DDS (domain 0) + camera RTP multicast
                     ┌──────── Jetson ──┴───────────────────────────┐
                     │ domain 0  : Go2 topics, go2_driver,          │
                     │             robot_state_publisher, ...       │
                     │      │ domain_bridge (~/dds/go2_bridge.yaml) │
                     │      ▼                                       │
                     │ domain 18 : high-level nodes, bridged topics,│
                     │             go2_camera (front camera images),│
                     │             go2_gps (/fix from UART GPS),    │
                     │             go2_imu (/imu/data from USB IMU) │
                     └──────────────────┬───────────────────────────┘
                                        │ wifi (wlP1p1s0, 192.168.0.253)
                                  laptops / RViz (domain 18)
```

- **Domain 0 = Go2 side, Ethernet only.** The Go2 firmware always publishes on domain 0
  and that cannot be changed. Nothing on domain 0 goes out over Wi-Fi.
- **Domain 18 = high-level side, Wi-Fi only.** Anything you run yourself (navigation,
  RViz, teleop) and any remote computer lives here.
- **`domain_bridge`** subscribes to topics on domain 0 and republishes them on domain 18
  (and `cmd_vel` the other way).
- **`go2_gps`** reads the HGLRC M100 mini GPS on the Jetson UART (`/dev/ttyTHS1`) and
  publishes `/fix` on domain 18 (see "GPS").
- **`go2_imu`** reads the WitMotion WT901 IMU on USB (`/dev/imu`) and publishes
  `/imu/data` and `/imu/mag` on domain 18 (see "IMU").
- **`go2_camera`** reads the front camera straight from the Go2's video stream on the
  Ethernet link and publishes images on domain 18 (see "Front camera").

Why split it:
- Go2 traffic (`/lowstate` at 500 Hz, point clouds, video) can't flood the Wi-Fi.
- If Wi-Fi drops, the robot side (domain 0) keeps running. Anything safety-critical,
  such as a `cmd_vel` timeout, belongs on domain 0.
- Normal shells default to domain 18, so a stray `ros2 topic pub` can't command the
  robot directly.

## Files

All of this is versioned in the `go2_backpack` git repo (`~/go2_backpack`, GitHub
`acard5meg/go2_backpack`). `~/go2_ws` and `~/dds` are symlinks into it; the system
files (systemd units, udev rule, sysctl, bashrc block) are copies in `system/`.

| File | Purpose |
|---|---|
| `~/dds/cyclonedds.xml` | Cyclone config for the Jetson. One `<Domain>` block per side; Cyclone picks the block matching each participant's domain ID, so one `CYCLONEDDS_URI` works for every process, including the bridge, which opens both domains. |
| `~/dds/go2_bridge.yaml` | `domain_bridge` config: which topics to copy, with type and QoS. |
| `~/dds/cyclonedds_laptop.xml` | Template for remote computers (domain 18 block only). |
| `~/dds/go2_run.sh` | Launcher used by the startup services (`driver`, `bridge` or `camera`). Sets up the ROS environment and waits for the network interfaces. |
| `~/.config/systemd/user/go2-driver.service`, `go2-bridge.service`, `go2-camera.service`, `go2-gps.service`, `go2-imu.service` | Start the driver, the bridge, the camera, GPS and IMU nodes on boot. See "Startup on boot". |
| `~/dds/logs/` | Output of the five services. |
| `~/go2_ws/src/go2_gps/` | The `go2_gps` package (NMEA GPS driver). |
| `~/go2_ws/src/go2_imu/` | The `go2_imu` package (WitMotion IMU driver). |
| `/etc/udev/rules.d/99-witmotion-imu.rules` | Names the IMU `/dev/imu`, keeps ModemManager off it. |
| `~/go2_ws/src/go2_camera/` | The `go2_camera` package (its own git repo, origin `acard5meg/go2_front_camera_feed`). |
| `~/.bashrc` | Sets up the environment (see below). Backup: `~/.bashrc.bak.2026-10-28`. |
| `~/unitree_ros2/setup.sh` | Unitree's setup script, edited to point at `~/dds/cyclonedds.xml`. Backup: `setup.sh.bak.2026-10-28`. The old single-domain config is still at `~/unitree_ros2/cyclonedds.xml` but is no longer used. |

## Cyclone config details

**Domain 0 (Ethernet):**
- Interface `enP8p1s0` only, `DontRoute` on.
- Multicast left on: it's a point-to-point link and the Go2 expects multicast discovery.

**Domain 18 (Wi-Fi):**
- Interface `wlP1p1s0` only.
- `AllowMulticast=spdp`: multicast is used **only for discovery**, so any computer on
  domain 18 finds the Jetson automatically with no peer list to maintain. Data is sent
  **unicast** to each subscriber. Full multicast would broadcast data (e.g. a point
  cloud) to every device on the Wi-Fi at the router's lowest rate.
- If a router blocks multicast entirely, discovery fails. The fallback is to add
  `<Discovery><Peers><Peer Address="..."/></Peers></Discovery>` with explicit IPs.

**Both domains:**
- `MaxMessageSize 65500B`.
- `SocketReceiveBufferSize max="10MB"`: asks for 10 MB and continues with less if the
  kernel limit is lower. Don't use `min=`; that makes Cyclone refuse to start when the
  limit is too low.

**Kernel buffer limit** (needed for large point clouds; one-time, needs sudo):
```bash
echo 'net.core.rmem_max=10485760' | sudo tee /etc/sysctl.d/60-cyclonedds.conf
sudo sysctl --system
sysctl net.core.rmem_max   # should print 10485760
```

## Bridge details

`~/dds/go2_bridge.yaml` was generated from `ros2 topic list -t` on domain 0 and lists
every Go2 topic, one per line. Comment lines out to stop bridging a topic.

- **Direction:** `from_domain: 0` → `to_domain: 18` for everything, except `cmd_vel`,
  which has `reversed: true` (Wi-Fi → robot). To command something else from a remote
  computer (e.g. `api/sport/request`), mark it `reversed: true`. **Never list the same
  topic in both directions**, or messages loop.
- **Latched topics:** `tf_static` and `robot_description` use
  `durability: transient_local, reliability: reliable`, so RViz gets them even if it
  starts after they were published.
- **Not bridged:**
  - `/rosout` and `/parameter_events`: each domain has its own.
  - `/lowstate` and `/lf/lowstate` (500 Hz / 20 Hz robot state, too heavy / not needed over Wi-Fi)
    and `/frontvideostream` (use the `go2_camera` topics instead). Disabled on purpose.
  - 9 topics are commented out because their message types aren't built on this Jetson:
    `unitree_arm/ArmString`, `unitree_interfaces/Qt*`, `unitree_interfaces/PcToImage`,
    `unitree_go/ConfigChangeStatus`. The bridge (and any subscriber) needs every type it
    carries, so those packages would have to be built here and on the remote computer.
- **Bridge creation is lazy per topic:** a bridge for a topic is created only once a
  publisher for it exists (so the QoS can be copied). Topics with no publisher, e.g.
  most `/api/*/request`, won't show on domain 18 until something publishes them.
- **Driver topics** (`tf`, `tf_static`, `robot_description`, `joint_states`, `scan`,
  `odom`, `pointcloud`, `imu`) only exist while `go2_driver` is running.

### Does it use bandwidth when nobody is watching?

- **Wi-Fi: no.** DDS only sends data to subscribers that have matched. With nobody
  subscribed on domain 18, Wi-Fi carries only discovery traffic (measured ~3 KB/s).
  When someone opens RViz, only the topics they subscribe to are sent, only to them.
- **Jetson CPU: yes.** The bridge subscribes to every listed topic on domain 0 all the
  time, so the Go2 streams everything over Ethernet and the bridge copies it into
  domain 18 regardless. Measured ~63% of one core (of 6) with all topics. The heavy
  ones, if you need to trim: `lowstate`, `lf/lowstate`, `utlidar/*` clouds,
  `frontvideostream`.

Measured on 2026-10-28: `/lowstate` 500 Hz on both domains, `/utlidar/cloud` ~14.7 Hz on
domain 18.

## Shell environment (`~/.bashrc`)

```bash
source /opt/ros/humble/setup.bash
source ~/go2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$HOME/dds/cyclonedds.xml"
export ROS_DOMAIN_ID=18
```

| Alias | Does |
|---|---|
| `go2_dom` | Switch the current shell to domain 0 (Go2 side) |
| `wifi_dom` | Switch the current shell back to domain 18 |
| `launch_go` | Start the Go2 driver stack on domain 0 |
| `go2_bridge` | Start the domain bridge |
| `go2_cam` | Start the front camera node on domain 18 |
| `go2_gps` | Start the GPS node on domain 18 |
| `go2_imu` | Start the IMU node on domain 18 |
| `unitree_setup`, `ros2_go` | Unchanged; source the Unitree / go2_ws workspaces |

## Front camera

The `go2_camera` package (`~/go2_ws/src/go2_camera`) publishes the Go2's front camera:

| Topic (domain 18) | Type | Use |
|---|---|---|
| `/go2_video_frames` | `sensor_msgs/Image`, 1280×720 `bgr8`, ~2.7 MB/frame | Nodes on the Jetson. **Don't view this over Wi-Fi** (~40 MB/s). |
| `/go2_video_frames/compressed` | `sensor_msgs/CompressedImage`, JPEG | Remote viewing. Measured 14.3 fps, ~1.6 MB/s. |

- **Source:** the node doesn't use the `/frontvideostream` DDS topic (it carried no data
  when tested). It reads the H264/RTP stream the Go2 multicasts to `230.1.1.1:1720` on
  the wired link, through GStreamer in OpenCV.
- **Why domain 18 directly:** the video arrives over UDP, not DDS, so there's nothing to
  bridge. Publishing straight on domain 18 avoids the bridge copying 2.7 MB frames.
- **Only works when someone's watching:** each topic is converted and published only
  while it has subscribers. Decoding runs all the time (~30% of one core idle, ~45%
  while publishing JPEG).
- **Frame:** images are stamped with `frame_id: Head_upper` (the URDF has no camera link).
- **Parameters** (launch args `multicast_iface` and `decoder`):
  `multicast_iface` (default `enP8p1s0`), `decoder` (`hw` = Jetson `nvv4l2decoder`,
  default; `sw` = `avdec_h264` on the CPU), `multicast_address`, `port`, `frame_id`,
  `jpeg_quality` (default 80).
- **Rebuild after changing the code:** `cd ~/go2_ws && colcon build --symlink-install
  --packages-select go2_camera`, then `systemctl --user restart go2-camera`.

**Viewing in RViz:** add an **Image** display and type the topic
`/go2_video_frames/compressed`. RViz on Humble picks the `compressed` transport from the
topic name; the laptop needs `ros-humble-compressed-image-transport` (part of
`ros-humble-image-transport-plugins`). Or use
`ros2 run rqt_image_view rqt_image_view` and pick the compressed topic.

## GPS

The `go2_gps` package (`~/go2_ws/src/go2_gps`) reads an HGLRC M100 mini (u-blox M10)
wired to the 40-pin header UART and publishes its position:

| Topic (domain 18) | Type | Notes |
|---|---|---|
| `/fix` | `sensor_msgs/NavSatFix` | 10 Hz (one per GGA sentence), `frame_id: gps` |

- **Port:** `/dev/ttyTHS1`, 115200 baud 8N1 (there is no `ttyTHS0` on this Jetson).
  `racecar` is in `dialout`, so no sudo is needed.
- **Decoding:** NMEA checksums are verified, and binary UBX bytes mixed into the stream
  are skipped. Position, fix quality, satellites and HDOP come from GGA. VDOP and the
  constellations in use come from GSA (from the previous epoch, since this receiver
  sends GSA after GGA).
- **No fix:** it still publishes, with `status: -1` (NO_FIX) and NaN position, so you can
  see the receiver is alive. The log prints "Fix acquired" / "No fix" when that changes.
- **Altitude** is height above the WGS84 ellipsoid (MSL altitude + geoid separation),
  as `NavSatFix` specifies.
- **Covariance:** approximated as `(HDOP × σ)²` horizontal and `(VDOP × σ)²` vertical,
  with σ = 4 m for a standalone fix (smaller for SBAS/RTK).
- **TF:** the launch file also publishes a static `base_link → gps` transform, at zero
  offset until the antenna mount is measured (launch args are `port`, `baud`,
  `frame_id`; edit the offsets in `go2_gps/launch/gps.launch.py`).
- **Why domain 18 directly:** like the camera, the data doesn't come from the Go2's DDS,
  so there's nothing to bridge.
- **Rebuild after changing the code:** `cd ~/go2_ws && colcon build --symlink-install
  --packages-select go2_gps`, then `systemctl --user restart go2-gps`.

Raw check without ROS:
```bash
stty -F /dev/ttyTHS1 115200 raw -echo && cat /dev/ttyTHS1 | grep -a GNGGA
# 7th field: fix quality (0 = none), 8th: satellites in use
```

## IMU

The `go2_imu` package (`~/go2_ws/src/go2_imu`) reads a WitMotion WT901 9-axis IMU on USB:

| Topic (domain 18) | Type | Notes |
|---|---|---|
| `/imu/data` | `sensor_msgs/Imu` | 100 Hz, orientation + angular velocity (rad/s) + acceleration (m/s², gravity included), `frame_id: imu_link` |
| `/imu/mag` | `sensor_msgs/MagneticField` | 100 Hz, **raw counts** (uncalibrated; set `mag_scale` in tesla/count after calibrating) |

Not to be confused with the Go2's own `/imu` (`unitree_go/IMUState`), which is bridged from domain 0.

- **Port:** `/dev/imu`, 115200 baud. A CH340 USB-serial chip built into the IMU. The
  udev rule `/etc/udev/rules.d/99-witmotion-imu.rules` gives it that fixed name, puts it in
  `dialout` and tells ModemManager to leave it alone.
- **brltty had to be removed** (`sudo apt remove brltty`): its udev rules claim every
  CH340 (`1a86:7523`) as a braille display and remove `/dev/ttyUSB0`.
- **IMU configuration (saved in the IMU's flash on 2026-10-28):** it came set to *no
  automatic output* (RRATE `0x0D`), so it was silent unless polled. Now:
  output content RSW = `0x021E` (accel, gyro, angle, mag, quaternion), rate RRATE = `0x09`
  (100 Hz), baud `0x06` (115200, unchanged). That's ~5.5 KB/s, about half the link.
- **Protocol:** 11-byte packets `0x55, type, 4 × int16 LE, checksum`. Types used:
  `0x51` accel (±16 g), `0x52` gyro (±2000 °/s), `0x53` Euler angles, `0x54` mag,
  `0x59` quaternion (w, x, y, z). One `Imu` message per cycle, sent when the quaternion
  arrives (or the angle packet, if quaternion output is turned off).
- **Orientation** is the WT901's own fusion. Yaw is relative to its magnetometer /
  start-up reference, not true north, until the magnetometer is calibrated.
- **Covariances** are fixed approximations (parameters `orientation_stddev`,
  `angular_velocity_stddev`, `linear_acceleration_stddev`).
- **TF:** the launch file publishes a static `base_link → imu_link` at zero offset and
  rotation. Set the real mount in `go2_imu/launch/imu.launch.py`.
- **Rebuild:** `cd ~/go2_ws && colcon build --symlink-install --packages-select go2_imu`,
  then `systemctl --user restart go2-imu`.

Changing the IMU's settings (stop `go2-imu` first). Each command is
`FF AA <reg> <low byte> <high byte>`; unlock before each write, save at the end:
```bash
systemctl --user stop go2-imu
python3 - <<'PY'
import serial, time
s = serial.Serial('/dev/imu', 115200)
def w(reg, val):
    s.write(bytes([0xFF, 0xAA, reg, val & 0xFF, val >> 8])); time.sleep(0.1)
w(0x69, 0xB588); w(0x03, 0x09)   # unlock; RRATE: 0x06=10 Hz 0x08=50 0x09=100 0x0B=200 0x0D=off
w(0x00, 0x0000)                  # save
PY
systemctl --user start go2-imu
```

## Startup on boot

The driver, the bridge, the camera, GPS and IMU nodes start automatically when the
Jetson boots (i.e. when the Go2 is powered on), as five **systemd user services** running as
`racecar`:

| Service | Runs | Log |
|---|---|---|
| `go2-driver` | `go2_run.sh driver` → `ros2 launch go2_bringup go2.launch.py` on domain 0 | `~/dds/logs/go2-driver.log` |
| `go2-bridge` | `go2_run.sh bridge` → `domain_bridge ~/dds/go2_bridge.yaml` | `~/dds/logs/go2-bridge.log` |
| `go2-camera` | `go2_run.sh camera` → `ros2 launch go2_camera camera_feed.launch.py` on domain 18 | `~/dds/logs/go2-camera.log` |
| `go2-gps` | `go2_run.sh gps` → `ros2 launch go2_gps gps.launch.py` on domain 18 | `~/dds/logs/go2-gps.log` |
| `go2-imu` | `go2_run.sh imu` → `ros2 launch go2_imu imu.launch.py` on domain 18 | `~/dds/logs/go2-imu.log` |

- `go2_run.sh` waits until `enP8p1s0` (driver) or both `enP8p1s0` and `wlP1p1s0`
  (bridge, camera) or `wlP1p1s0` (gps, imu) have an IPv4 address before starting, because Cyclone can't create a
  domain on an interface with no address.
- All have `Restart=always` (5 s delay), so a crash or a failed start retries on its own.
- They're stopped with SIGINT and `KillMode=mixed`: the signal goes only to `ros2 launch`,
  which shuts its nodes down in order. With the default `KillMode` every node got SIGINT
  twice (from systemd and from launch), and Python nodes crashed during cleanup.
- The services don't read `~/.bashrc`; their environment is set in `go2_run.sh`. If you
  change workspaces or configs, update it there too.
- **Requires linger** so user services start at boot without anyone logging in
  (one-time, needs sudo):
  ```bash
  sudo loginctl enable-linger racecar
  loginctl show-user racecar -p Linger   # should print Linger=yes
  ```

Managing them:
```bash
systemctl --user status go2-driver go2-bridge go2-camera go2-gps go2-imu
systemctl --user restart go2-bridge          # e.g. after editing go2_bridge.yaml
systemctl --user stop go2-driver go2-bridge go2-camera go2-gps go2-imu  # e.g. to run things by hand
systemctl --user disable go2-driver          # don't start on boot anymore
tail -f ~/dds/logs/go2-bridge.log
```

The log files are appended to and never rotated; clear them occasionally
(`: > ~/dds/logs/go2-driver.log`).

### Running by hand

Stop the services first (`systemctl --user stop go2-driver go2-bridge go2-camera go2-gps go2-imu`),
otherwise you get two of each. Then, in separate terminals:
```bash
launch_go      # driver on domain 0
go2_bridge     # bridge 0 -> 18
go2_cam        # front camera on domain 18
go2_gps        # GPS on domain 18
go2_imu        # IMU on domain 18
```

## Setting up a remote computer (laptop)

1. Copy `~/dds/cyclonedds_laptop.xml` to it and replace `CHANGE_ME_wifi_iface` with its
   Wi-Fi interface name (`ip -br addr`). It lists the Jetson (192.168.0.253) as a unicast
   peer. Keep that: on this router, multicast from the computer didn't reach the Jetson,
   so the computer could see topics but the Jetson never discovered its subscribers
   (see Troubleshooting). If the Jetson's IP changes, update the peer.
2. Environment:
   ```bash
   export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
   export ROS_DOMAIN_ID=18
   export CYCLONEDDS_URI=file:///path/to/cyclonedds_laptop.xml
   ```
3. Build these from `~/go2_ws/src` on the laptop:
   - `go2_description`: RViz needs the meshes locally (`package://` paths), or the
     robot model won't show.
   - `unitree_go`, `unitree_api`: needed to view Unitree message types.
4. Install `ros-humble-image-transport-plugins` to view the compressed camera topic.
5. Open RViz with fixed frame `odom` (or `base_link`).

Any number of computers can join this way; nothing on the Jetson needs to change.

## Checking it works

```bash
# Jetson
ROS_DOMAIN_ID=0  ros2 topic list | wc -l     # Go2 topics (~121)
ROS_DOMAIN_ID=18 ros2 topic list | wc -l     # bridged topics
ROS_DOMAIN_ID=18 ros2 topic hz /lowstate     # should be ~500 Hz
ps -C domain_bridge -o %cpu                  # bridge CPU

# Wi-Fi transmit rate over 10 s
r(){ awk -v i=$1 '$1==i":"{print $10}' /proc/net/dev; }
a=$(r wlP1p1s0); sleep 10; echo "$(( ($(r wlP1p1s0)-a)/10240 )) KB/s"
```

## Troubleshooting

- **`failed to increase socket receive buffer size` + `failed to create domain`:**
  the XML uses `min=` on `SocketReceiveBufferSize`. Use `max=`, or raise `rmem_max`.
- **Bridge aborts with `YAML::ParserException`:** check the line it names. Comments
  must go after the closing `}`, never inside the braces.
- **Laptop sees a topic but `echo` gets nothing:** the Jetson hasn't discovered the
  laptop (multicast from the laptop isn't reaching it), so no data is sent. On the
  Jetson, `ros2 topic info -v <topic>` shows no remote subscriber. Fix: the
  `<Peers><Peer Address="192.168.0.253"/></Peers>` entry in the laptop's XML, then
  `ros2 daemon stop` on the laptop. Topics that "still work" in an RViz that was already
  open are riding on a connection made earlier; new processes need fresh discovery.
- **Laptop sees no topics:** check `ROS_DOMAIN_ID=18`, the `RMW_IMPLEMENTATION`, the
  interface name in the XML, and whether the router passes multicast (if not, add peers).
- **No robot model in RViz:** `go2_description` missing on the laptop, or RViz started
  before the bridge and `robot_description`/`tf_static` QoS was changed from
  transient_local.
- **Wi-Fi dropped:** domain-18 participants on the Jetson don't recover well when the
  interface disappears. Restart the bridge (`systemctl --user restart go2-bridge`) and
  any other domain-18 nodes. Domain 0 is unaffected.
- **Services didn't start after a reboot:** check `loginctl show-user racecar -p Linger`
  (must be `yes`), then `systemctl --user status go2-driver go2-bridge` and the logs in
  `~/dds/logs/`. `journalctl --user` doesn't work on this Jetson (no persistent user
  journal), which is why the services log to files.
- **`/fix` always NO_FIX:** check the raw stream (see "GPS"). `GxGSV` with `00`
  satellites means the antenna can't see the sky: go outdoors, antenna up, and give a
  cold start a few minutes. Keep it away from USB 3.0 ports and the Go2's electronics,
  which can jam GPS. No data at all: check wiring (GPS TX → Jetson RX, GPS RX → Jetson TX, GND,
  5 V) and `~/dds/logs/go2-gps.log`.
- **No `/dev/imu` / `/dev/ttyUSB0` vanishes right after plugging in:** brltty is back
  (`dpkg -l brltty`), or the udev rule is missing. `journalctl -k | grep ch341`.
- **`/imu/data` silent, log says "No data ... for 2 s":** the IMU's output rate is off
  (RRATE `0x0D`); set it again (see "IMU"). Check with
  `python3 -c "import serial;print(serial.Serial('/dev/imu',115200,timeout=1).read(50).hex())"`
  (with `go2-imu` stopped): the output should be full of `55 51`, `55 52`, ...
- **Ethernet to the Go2 unplugged / Go2 off:** the driver log fills with
  `ddsi_udp_conn_write ... failed`. Domain 0 recovers by itself once the link is back
  (tested); no restart needed.
- **No camera images:** check `~/dds/logs/go2-camera.log` (it logs the GStreamer
  pipeline it opened). The node subscribes to the video multicast on `enP8p1s0`; if it
  publishes nothing, test the stream directly with GStreamer on that interface.
- **Raw `/go2_video_frames` drops frames or arrives very slowly:** the kernel socket
  buffer is too small for 2.7 MB messages. Raise `net.core.rmem_max` (see "Cyclone
  config details"), or use the compressed topic.
- **Wi-Fi slow / high ping while RViz is open:** check the `/tf` rate
  (`ros2 topic hz /tf`). `robot_state_publisher` must run with `use_sim_time:=False`
  (default set in `go2_description/launch/robot.launch.py`, line 52). With sim time on
  and no `/clock`, it ignores `publish_frequency` and republishes TF for every
  500 Hz `/joint_states` message (~500 Hz `/tf`); with it off, `/tf` is ~90 Hz.
- **Topic missing on domain 18:** it must be listed in `go2_bridge.yaml` *and* have a
  publisher on domain 0 (`ROS_DOMAIN_ID=0 ros2 topic info /topic`). After editing the
  YAML, `systemctl --user restart go2-bridge`.
- **Nothing works after sourcing `unitree_setup`:** check `echo $CYCLONEDDS_URI`; it
  should be `~/dds/cyclonedds.xml`.

## To do

The full, ranked list (networking, robustness, usability) is in section 15 of
`~/dds/full_writeup.txt`. Odometry / driver items:

- **`/odom` depends on an uncommitted edit.** Upstream `go2_driver` publishes `/odom`
  once and stops (`odom_published_ = true`); line 167 of `go2_driver.cpp` is commented
  out locally to make it continuous. Commit it, or turn it into a parameter.
- **`/odom` has no velocity.** `twist` is always zero, so Nav2 / robot_localization
  can't use it for velocity. Fill it from `/sportmodestate` or `/utlidar/robot_odom`.
- **`/odom` has no covariance** (all zeros = unknown). Add realistic values.
- **Consider a faster source:** `/odom` is built from `/utlidar/robot_pose` (~19 Hz, pose
  only). `/utlidar/robot_odom` (~150 Hz, full Odometry) and `/sportmodestate` (~300 Hz,
  leg odometry with velocity) are available on domain 0. Keep TF and `/odom` from the
  same source.
- **Hard-coded +0.07 m z offset** on `odom → base_link` and `/odom`: make it a parameter
  and check it against the URDF.
- **Timestamps:** the driver restamps with the Jetson's time, hiding the lidar latency.
  Using the Go2's stamps needs the two clocks in sync.

How `/odom` is produced today:
```
Go2 ─/utlidar/robot_pose (PoseStamped, ~19 Hz)─▶ go2_driver (go2_driver.cpp:138-169)
     ├─▶ TF odom → base_link   (z + 0.07 m)
     └─▶ /odom (Odometry, pose only, reliable + transient_local) ─bridge─▶ domain 18
```
