# Instructions for your laptop
- This guide is the minimum amount you need to do to work with the Go2.
- Unitree publishes custom messages so you need to build their workspace.
- At this point, I'm unsure if you need the Go2 driver on your computer (Need feedback)

## Getting into Go2 Computer:

- If you need to get into Go2's onboard computer you must be wired in and on the 192.168.123.XX network
- `ssh unitree@192.168.123.18`
    - password: 123

## Backpack Compute

- Jetson Orin Nano
    - Taken from Neobotics NeoRacer v1.
        - Overview of pre-installed packages: https://neobotics.org/docs
    - username: racecar
    - hostname: neoracer
    - password: neobotics
        - Full password list: https://neobotics.org/docs/reference/passwords
    - software: Ubuntu 22.04 jammy
    - ros version: Ros2 humble
- Networking
    - Manual IPv4 for Wired Connection
        - Address: 192.168.123.99
        - Netmask: 255.255.255.0
    - Connecting with your own machine
        - Wired connection and set your own static IP
            - Address: 192.168.123.XX
            - Netmask: 255.255.255.0
        - `ssh racecar@192.168.123.99`
        - password: neobotics
    - The Jetson has wifi antenna attached. It should connect automatically to TP-LINK_A4CC
        - Password: 43921126
    - If you need internet on the Jetson and you are hardwired your machine can work as the DHCP/NAT server by using ‘Shared to other computers’ for the link

## Go2 Unitree SDK

- https://github.com/unitreerobotics/unitree_ros2
- Follow instructions on GitHub, clone repository into home directory
- For Humble, skip step 2: compiling the cyclonedds
- For step 3 ensure you’re in the unitree_ros2 directory and humble is sourced
    
    ```jsx
    cd ~/unitree_ros2
    source /opt/ros/humble/setup.bash
    colcon build
    ```
- This will likely generate a few warnings. I received the following:
- -Wclass-memaccess
    - warning: ‘void* memcpy(void*, const void*, size_t)’ copying an object of non-trivial type...
    - This is a known, harmless mismatch between specific versions of GCC and the Eigen linear algebra library. GCC flags it because Eigen uses `memcpy` on a custom data type (`eigen_packet_wrapper`).
    - FIX: Nothing to do, internal code library
- backslash-newline
    - warning: backslash-newline at end of file
    - In `ut_errror.hpp`, a macro definition ends with a line-continuation backslash (`\`), but there is no empty newline following it at the very bottom of the file.
    - FIX-Implemented: If you want to clean up your terminal output, open `/home/racecar/unitree_ros2/example/src/include/common/ut_errror.hpp`. Go to the very last line, hit `Enter` to create a blank line at the bottom, and save the file.

## Unitree Go2 Driver - Unsure if you need to do this

- Unitree publishes custom message and topics
- We can see and echo them using the DDS middleware, but common ROS topics such as /odom, /cmd_vel, /pointcloud, /tf are missing. This repo rectifies this
- Install the following
    - `sudo apt install ros-humble-realsense2-camera ros-humble-xacro ros-humble-pointcloud-to-laserscan`
- https://github.com/Unitree-Go2-Robot/go2_robot/tree/humble
    - Follow README until Sensor Installation

## Sourcing everything at once
```
source <path to file>/go2_overlay_setup.sh
```