from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    port = LaunchConfiguration('port')
    baud = LaunchConfiguration('baud')
    frame_id = LaunchConfiguration('frame_id')

    declare_port_cmd = DeclareLaunchArgument(
        'port',
        default_value='/dev/imu',
        description='Serial port of the IMU (udev symlink to the CH340 ttyUSB)'
    )

    declare_baud_cmd = DeclareLaunchArgument(
        'baud',
        default_value='115200',
        description='Serial baud rate'
    )

    declare_frame_id_cmd = DeclareLaunchArgument(
        'frame_id',
        default_value='imu_link',
        description='frame_id stamped on /imu/data and /imu/mag'
    )

    imu_node = Node(
        package='go2_imu',
        executable='imu_node',
        name='go2_imu',
        output='screen',
        parameters=[{
            'port': port,
            'baud': baud,
            'frame_id': frame_id,
        }]
    )

    # IMU position and orientation relative to base_link. Zero until the mount
    # is measured (x forward, y left, z up, metres; yaw/pitch/roll in rad).
    imu_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='imu_static_tf',
        arguments=['--x', '0', '--y', '0', '--z', '0',
                   '--yaw', '0', '--pitch', '0', '--roll', '0',
                   '--frame-id', 'base_link', '--child-frame-id', frame_id],
    )

    return LaunchDescription([
        declare_port_cmd,
        declare_baud_cmd,
        declare_frame_id_cmd,
        imu_node,
        imu_tf,
    ])
