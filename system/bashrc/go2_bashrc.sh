alias ros2_go="source $HOME/go2_ws/install/setup.bash"

# ---- Go2 DDS split: domain 0 = Go2 over eth, domain 18 = high-level over wifi ----
# Configs live in ~/dds (cyclonedds.xml has one <Domain> block per side).
source /opt/ros/humble/setup.bash
[ -f $HOME/go2_ws/install/setup.bash ] && source $HOME/go2_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$HOME/dds/cyclonedds.xml"
export ROS_DOMAIN_ID=18                       # default shells = wifi / high-level side
alias go2_dom='export ROS_DOMAIN_ID=0'        # switch this shell to the Go2 side
alias wifi_dom='export ROS_DOMAIN_ID=18'      # switch this shell back to the wifi side
alias launch_go='ROS_DOMAIN_ID=0 ros2 launch go2_bringup go2.launch.py'
alias go2_bridge='ros2 run domain_bridge domain_bridge $HOME/dds/go2_bridge.yaml'
alias go2_cam='ROS_DOMAIN_ID=18 ros2 launch go2_camera camera_feed.launch.py'
alias go2_gps='ROS_DOMAIN_ID=18 ros2 launch go2_gps gps.launch.py'
alias go2_imu='ROS_DOMAIN_ID=18 ros2 launch go2_imu imu.launch.py'
