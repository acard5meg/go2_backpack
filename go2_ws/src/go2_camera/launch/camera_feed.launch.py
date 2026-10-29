from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    multicast_iface = LaunchConfiguration('multicast_iface')
    decoder = LaunchConfiguration('decoder')

    declare_multicast_iface_cmd = DeclareLaunchArgument(
        'multicast_iface',
        default_value='enP8p1s0',
        description='Network interface wired to the Go2'
    )

    declare_decoder_cmd = DeclareLaunchArgument(
        'decoder',
        default_value='hw',
        description="H264 decoder: 'hw' (Jetson hardware) or 'sw' (CPU)"
    )

    # Create the node
    go2_camera_node = Node(
        package='go2_camera',
        executable='camera_node',
        name='camera_node',
        output='screen',
        parameters=[{
            'multicast_iface': multicast_iface,
            'decoder': decoder,
        }]
    )

    return LaunchDescription([
        declare_multicast_iface_cmd,
        declare_decoder_cmd,
        go2_camera_node
    ])
