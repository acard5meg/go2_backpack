# go2_backpack

Everything that runs on the Jetson "backpack" mounted on a Unitree Go2: the ROS 2 Humble
workspace, the CycloneDDS two-domain network split, the domain bridge, the front camera,
GPS and IMU drivers, and the systemd services that start it all on boot.

```
 Go2 ──eth (domain 0)──▶ Jetson: go2_driver, robot_state_publisher, ...
                            │ domain_bridge (dds/go2_bridge.yaml)
                            ▼
                         domain 18: bridged topics + go2_camera, go2_gps, go2_imu
                            │
                         Wi-Fi (domain 18) ──▶ laptops / RViz
```

## Documentation

- [`dds/README.md`](dds/README.md): reference for the network split, bridge, camera,
  GPS, IMU, services, laptop setup and troubleshooting.
- [`dds/full_writeup.txt`](dds/full_writeup.txt): the long version, with every problem
  hit so far and how it was fixed, a debugging guide with commands, measured baselines
  and the to-do list.

## Layout

| Path | What |
|---|---|
| `go2_ws/src/` | ROS 2 workspace sources (build with colcon) |
| `go2_ws/src/go2_gps` | NMEA GPS driver (HGLRC M100 mini on `/dev/ttyTHS1`) → `/fix` |
| `go2_ws/src/go2_imu` | WitMotion WT901 driver (`/dev/imu`) → `/imu/data`, `/imu/mag` |
| `go2_ws/src/go2_camera` | Go2 front camera → `/go2_video_frames` + `/compressed` (from [acard5meg/go2_front_camera_feed](https://github.com/acard5meg/go2_front_camera_feed)) |
| `go2_ws/src/go2_*`, `unitree_*` | Go2 driver stack, vendored from [Unitree-Go2-Robot](https://github.com/Unitree-Go2-Robot) (Apache-2.0) **with local changes**, see below |
| `dds/` | CycloneDDS configs, bridge YAML, service launcher `go2_run.sh`, docs |
| `system/systemd/` | `go2-{driver,bridge,camera,gps,imu}.service` (systemd user units) |
| `system/udev/` | `99-witmotion-imu.rules`: names the IMU `/dev/imu` |
| `system/sysctl/` | `60-cyclonedds.conf`: 10 MB socket receive buffer |
| `system/bashrc/go2_bashrc.sh` | environment and aliases (`go2_dom`, `wifi_dom`, `launch_go`, ...) |
| `install.sh` | sets all of the above up on a Jetson |

### Local changes to the vendored Unitree-Go2-Robot packages

- `go2_description/launch/robot.launch.py`: `use_sim_time` defaults to `False`. With
  `True`, `/tf` ran at ~500 Hz and flooded the Wi-Fi.
- `go2_description/urdf/go2_description.urdf`: empty `base_link` + fixed joint to `base_body`.
- `go2_driver/src/go2_driver/go2_driver.cpp`: `odom_published_ = true;` commented out so
  `/odom` publishes continuously (upstream publishes it once).
- `go2_bringup/launch/go2.launch.py`: Hesai lidar and RealSense includes commented out.

## Install on a Jetson

Assumes JetPack 6 / Ubuntu 22.04, ROS 2 Humble in `/opt/ros/humble`, and user `racecar`
(the service files and `go2_run.sh` use `/home/racecar`).

```bash
git clone https://github.com/acard5meg/go2_backpack.git ~/go2_backpack
cd ~/go2_backpack
./install.sh          # asks for sudo for apt, udev, sysctl and linger
```

`install.sh` links `~/go2_ws` and `~/dds` to the repo, installs dependencies, builds the
workspace, installs the udev rule, sysctl setting and systemd units, adds the bashrc
snippet, and enables the services. See the script for the individual steps.

Not covered by the script:
- Removing `brltty` if a CH340 device vanishes right after plugging in
  (`sudo apt remove brltty`, see `dds/README.md` → IMU).
- Locking the Wi-Fi to 5 GHz (`nmcli connection modify <ssid> 802-11-wireless.band a`).
- Setting the WitMotion IMU to stream at 100 Hz (stored on the IMU; see `dds/README.md` → IMU).
- Laptop setup: copy `dds/cyclonedds_laptop.xml` (see `dds/README.md`).

## On this Jetson

The repo lives at `~/go2_backpack`, and `~/go2_ws` and `~/dds` are symlinks into it,
so the services and docs keep using those paths. The files in `system/` are copies:
after changing an installed unit, rule or the bashrc block, copy it back here (or edit
here and re-run the matching `install.sh` step).
