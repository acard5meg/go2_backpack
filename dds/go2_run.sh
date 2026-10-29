#!/bin/bash
# Launcher used by the systemd user services (go2-driver / go2-bridge / go2-camera / go2-gps /
# go2-imu).
# Usage: go2_run.sh driver|bridge|camera|gps|imu
set -e

source /opt/ros/humble/setup.bash
source /home/racecar/go2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file:///home/racecar/dds/cyclonedds.xml"

# Cyclone fails to create a domain if its interface has no IPv4 address yet,
# so wait for it instead of crash-looping at boot.
wait_for_ip() {
    until ip -4 addr show dev "$1" 2>/dev/null | grep -q 'inet '; do
        echo "waiting for $1 to get an IPv4 address..."
        sleep 2
    done
}

case "$1" in
    driver)
        wait_for_ip enP8p1s0
        export ROS_DOMAIN_ID=0
        exec ros2 launch go2_bringup go2.launch.py
        ;;
    bridge)
        wait_for_ip enP8p1s0
        wait_for_ip wlP1p1s0
        exec ros2 run domain_bridge domain_bridge /home/racecar/dds/go2_bridge.yaml
        ;;
    camera)
        # Video comes from the Go2's multicast RTP stream on eth (not DDS),
        # so publish straight onto the wifi domain instead of bridging it.
        wait_for_ip enP8p1s0
        wait_for_ip wlP1p1s0
        export ROS_DOMAIN_ID=18
        exec ros2 launch go2_camera camera_feed.launch.py
        ;;
    gps)
        # GNSS receiver on the Jetson UART, not part of the Go2's DDS, so
        # publish straight onto the wifi domain like the camera.
        wait_for_ip wlP1p1s0
        export ROS_DOMAIN_ID=18
        exec ros2 launch go2_gps gps.launch.py
        ;;
    imu)
        # WitMotion IMU on USB (/dev/imu), not part of the Go2's DDS, so
        # publish straight onto the wifi domain like the camera.
        wait_for_ip wlP1p1s0
        export ROS_DOMAIN_ID=18
        exec ros2 launch go2_imu imu.launch.py
        ;;
    *)
        echo "usage: $0 driver|bridge|camera|gps|imu" >&2
        exit 1
        ;;
esac
