#!/bin/bash
echo "Setup unitree ros2 environment"
source /opt/ros/humble/setup.bash
# source $HOME/unitree_ros2/cyclonedds_ws/install/setup.bash
export ROS_DOMAIN_ID=18
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file:///<INSERT PATH TO >/cyclonedds_laptop.xml"
source $HOME/unitree_ros2/install/setup.bash
source $HOME/go2_ws/install/setup.bash