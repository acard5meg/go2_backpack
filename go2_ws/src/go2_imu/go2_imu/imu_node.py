import math
import struct
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import Imu, MagneticField
import serial


G = 9.80665
PACKET_LEN = 11

ACCEL = 0x51
GYRO = 0x52
ANGLE = 0x53
MAG = 0x54
QUAT = 0x59


def parse_packets(buffer):
    """
    Split a byte buffer into valid WitMotion packets.

    Each packet is 0x55, type, 8 data bytes (4 little-endian int16), and a
    checksum (low byte of the sum of the first 10 bytes). Returns the
    (type, values) of every valid packet and the unconsumed tail of the buffer.
    """
    packets = []
    i = 0
    while i + PACKET_LEN <= len(buffer):
        # A stray 0x55 inside the data can pass the 8-bit checksum by chance,
        # so require a valid type byte too.
        if buffer[i] != 0x55 or not 0x50 <= buffer[i + 1] <= 0x5F:
            i += 1
            continue
        packet = buffer[i:i + PACKET_LEN]
        if sum(packet[:10]) & 0xFF != packet[10]:
            i += 1
            continue
        packets.append((packet[1], struct.unpack('<hhhh', packet[2:10])))
        i += PACKET_LEN
    return packets, buffer[i:]


def euler_to_quaternion(roll, pitch, yaw):
    """ZYX Euler angles (rad) -> (x, y, z, w)."""
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return (sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
            cr * cp * cy + sr * sp * sy)


class Go2ImuNode(Node):
    """
    Reads a WitMotion WT901 streaming its standard serial protocol (accel,
    gyro, angle, mag, quaternion packets) and publishes sensor_msgs/Imu on
    'imu/data' and sensor_msgs/MagneticField on 'imu/mag'.

    One Imu message is published per output cycle, when its last packet
    arrives: the quaternion if the sensor sends one, otherwise the angle.
    """

    def __init__(self):
        super().__init__('go2_imu')

        self.declare_parameter('port', '/dev/imu')
        self.declare_parameter('baud', 115200)
        self.declare_parameter('frame_id', 'imu_link')
        # 1-sigma noise for the covariance diagonals. Rough figures from the
        # WT901 datasheet; tune if a filter downstream needs better ones.
        self.declare_parameter('orientation_stddev', [0.01, 0.01, 0.035])  # rad
        self.declare_parameter('angular_velocity_stddev', 0.002)  # rad/s
        self.declare_parameter('linear_acceleration_stddev', 0.04)  # m/s^2
        # The WT901 reports the magnetometer in raw counts. 1.0 publishes those
        # counts as-is; set the tesla-per-count factor after calibrating.
        self.declare_parameter('mag_scale', 1.0)

        self.port = self.get_parameter('port').value
        self.baud = self.get_parameter('baud').value
        self.frame_id = self.get_parameter('frame_id').value
        self.mag_scale = self.get_parameter('mag_scale').value

        orientation_stddev = self.get_parameter('orientation_stddev').value
        gyro_var = self.get_parameter('angular_velocity_stddev').value ** 2
        accel_var = self.get_parameter('linear_acceleration_stddev').value ** 2
        self.orientation_cov = [0.0] * 9
        for i, stddev in enumerate(orientation_stddev):
            self.orientation_cov[i * 4] = stddev ** 2
        self.gyro_cov = [gyro_var, 0.0, 0.0, 0.0, gyro_var, 0.0, 0.0, 0.0, gyro_var]
        self.accel_cov = [accel_var, 0.0, 0.0, 0.0, accel_var, 0.0, 0.0, 0.0, accel_var]

        self.imu_publisher = self.create_publisher(Imu, 'imu/data', 10)
        self.mag_publisher = self.create_publisher(MagneticField, 'imu/mag', 10)

        self.accel = None
        self.gyro = None
        self.orientation = None
        self.has_quat = False

        # serial reads block, so read in a thread rather than a timer.
        self.running = True
        self.thread = threading.Thread(target=self.read_loop, daemon=True)
        self.thread.start()

    def read_loop(self):
        ser = None
        buffer = b''
        last_data = time.monotonic()
        while self.running and rclpy.ok():
            if ser is None:
                try:
                    ser = serial.Serial(self.port, self.baud, timeout=1.0)
                    self.get_logger().info(f'Opened {self.port} at {self.baud} baud')
                    buffer = b''
                    last_data = time.monotonic()
                except serial.SerialException as e:
                    self.get_logger().error(
                        f'Cannot open {self.port}: {e}. Retrying in 2 s',
                        throttle_duration_sec=30.0)
                    time.sleep(2.0)
                    continue

            try:
                # Block for the first byte, then take everything waiting.
                chunk = ser.read(max(1, ser.in_waiting))
            except (serial.SerialException, OSError) as e:
                self.get_logger().error(f'Serial error on {self.port}: {e}. Reopening')
                ser.close()
                ser = None
                continue

            if not chunk:
                if time.monotonic() - last_data > 2.0:
                    self.get_logger().warn(
                        f'No data from {self.port} for 2 s. Is the IMU output '
                        'rate set to streaming (RRATE)?',
                        throttle_duration_sec=30.0)
                continue
            last_data = time.monotonic()

            packets, buffer = parse_packets(buffer + chunk)
            for kind, values in packets:
                self.handle_packet(kind, values)

        if ser is not None:
            ser.close()

    def handle_packet(self, kind, values):
        a, b, c, d = values
        if kind == ACCEL:
            scale = 16.0 * G / 32768.0
            self.accel = (a * scale, b * scale, c * scale)
        elif kind == GYRO:
            scale = math.radians(2000.0) / 32768.0
            self.gyro = (a * scale, b * scale, c * scale)
        elif kind == ANGLE:
            if not self.has_quat:
                scale = math.pi / 32768.0
                self.orientation = euler_to_quaternion(a * scale, b * scale, c * scale)
                self.publish_imu()
        elif kind == QUAT:
            # Sent as w, x, y, z
            self.has_quat = True
            self.orientation = (b / 32768.0, c / 32768.0, d / 32768.0, a / 32768.0)
            self.publish_imu()
        elif kind == MAG:
            self.publish_mag(a, b, c)

    def publish_imu(self):
        if self.accel is None or self.gyro is None or self.orientation is None:
            return
        if not rclpy.ok():
            return

        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        (msg.orientation.x, msg.orientation.y,
         msg.orientation.z, msg.orientation.w) = self.orientation
        msg.orientation_covariance = self.orientation_cov
        (msg.angular_velocity.x, msg.angular_velocity.y,
         msg.angular_velocity.z) = self.gyro
        msg.angular_velocity_covariance = self.gyro_cov
        (msg.linear_acceleration.x, msg.linear_acceleration.y,
         msg.linear_acceleration.z) = self.accel
        msg.linear_acceleration_covariance = self.accel_cov
        self.imu_publisher.publish(msg)

    def publish_mag(self, x, y, z):
        if not rclpy.ok():
            return
        msg = MagneticField()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        msg.magnetic_field.x = x * self.mag_scale
        msg.magnetic_field.y = y * self.mag_scale
        msg.magnetic_field.z = z * self.mag_scale
        self.mag_publisher.publish(msg)

    def stop(self):
        self.running = False
        self.thread.join(timeout=2.0)


def main(args=None):
    rclpy.init(args=args)
    imu = Go2ImuNode()

    try:
        rclpy.spin(imu)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        imu.stop()
        # On SIGINT/SIGTERM rclpy has already shut the context down, and
        # destroy_node() then raises on Humble, so only destroy while it's valid.
        if rclpy.ok():
            imu.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
