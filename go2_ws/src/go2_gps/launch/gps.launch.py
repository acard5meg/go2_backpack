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
        default_value='/dev/ttyTHS1',
        description='Serial port of the GNSS receiver (40-pin header UART)'
    )

    declare_baud_cmd = DeclareLaunchArgument(
        'baud',
        default_value='115200',
        description='Serial baud rate'
    )

    declare_frame_id_cmd = DeclareLaunchArgument(
        'frame_id',
        default_value='gps',
        description='frame_id stamped on /fix'
    )

    gps_node = Node(
        package='go2_gps',
        executable='gps_node',
        name='go2_gps',
        output='screen',
        parameters=[{
            'port': port,
            'baud': baud,
            'frame_id': frame_id,
        }]
    )

    # Antenna position relative to base_link. Zero until the mount is measured
    # (x forward, y left, z up, metres).
    gps_tf = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='gps_static_tf',
        arguments=['--x', '0', '--y', '0', '--z', '0',
                   '--frame-id', 'base_link', '--child-frame-id', frame_id],
    )

    return LaunchDescription([
        declare_port_cmd,
        declare_baud_cmd,
        declare_frame_id_cmd,
        gps_node,
        gps_tf,
    ])
