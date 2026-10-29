from setuptools import setup
import os
from glob import glob

package_name = 'go2_gps'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Alexandyr Card',
    maintainer_email='alexandyrtcard@gmail.com',
    description='NMEA GNSS driver for the Go2 Jetson (HGLRC M100 mini), publishes /fix',
    license='Apache License 2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'gps_node = go2_gps.gps_node:main'
        ],
    },
)
