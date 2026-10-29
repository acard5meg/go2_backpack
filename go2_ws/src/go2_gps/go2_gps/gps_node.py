import math
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix, NavSatStatus
import serial


# GGA fix quality -> NavSatStatus.status
FIX_STATUS = {
    0: NavSatStatus.STATUS_NO_FIX,
    1: NavSatStatus.STATUS_FIX,       # autonomous GNSS
    2: NavSatStatus.STATUS_SBAS_FIX,  # DGPS / SBAS
    4: NavSatStatus.STATUS_GBAS_FIX,  # RTK fixed
    5: NavSatStatus.STATUS_GBAS_FIX,  # RTK float
    6: NavSatStatus.STATUS_FIX,       # dead reckoning
}

# GGA fix quality -> rough 1-sigma user range error in metres, scaled by DOP
# to get the position covariance.
UERE = {1: 4.0, 2: 1.0, 4: 0.02, 5: 0.5, 6: 10.0}

# GSA system ID (NMEA 4.10+) -> NavSatStatus.service bit
SERVICE = {
    1: NavSatStatus.SERVICE_GPS,
    2: NavSatStatus.SERVICE_GLONASS,
    3: NavSatStatus.SERVICE_GALILEO,
    4: NavSatStatus.SERVICE_COMPASS,  # BeiDou
}


def parse_sentence(line):
    """Return the comma-separated fields of a valid NMEA sentence, or None."""
    start = line.find('$')
    if start < 0:
        return None
    body, sep, checksum = line[start + 1:].partition('*')
    if not sep or len(checksum) < 2:
        return None
    calculated = 0
    for c in body:
        calculated ^= ord(c)
    try:
        if calculated != int(checksum[:2], 16):
            return None
    except ValueError:
        return None
    return body.split(',')


def nmea_to_degrees(value, hemisphere):
    """Convert NMEA ddmm.mmmm / dddmm.mmmm plus N/S/E/W to signed degrees."""
    raw = float(value)
    degrees = int(raw // 100)
    result = degrees + (raw - degrees * 100) / 60.0
    return -result if hemisphere in ('S', 'W') else result


def to_float(value, default=float('nan')):
    try:
        return float(value)
    except ValueError:
        return default


class Go2GpsNode(Node):
    """
    Reads NMEA from a serial GNSS receiver (HGLRC M100 mini on the Jetson UART)
    and publishes sensor_msgs/NavSatFix on 'fix', once per GGA sentence (1 Hz by
    default). Without a fix it still publishes, with status NO_FIX and NaN
    position, so subscribers can see the receiver is alive.
    """

    def __init__(self):
        super().__init__('go2_gps')

        self.declare_parameter('port', '/dev/ttyTHS1')
        self.declare_parameter('baud', 115200)
        self.declare_parameter('frame_id', 'gps')

        self.port = self.get_parameter('port').value
        self.baud = self.get_parameter('baud').value
        self.frame_id = self.get_parameter('frame_id').value

        self.fix_publisher = self.create_publisher(NavSatFix, 'fix', 10)

        # DOP and constellations come from GSA, which this receiver sends after
        # GGA, so each fix uses the values from the previous epoch.
        self.vdop = float('nan')
        self.service = 0
        self.gsa_service = 0
        self.last_quality = None

        # serial.readline() blocks, so read in a thread rather than a timer.
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
                # readline() reads one byte per call and costs a lot of CPU.
                chunk = ser.read(max(1, ser.in_waiting))
            except (serial.SerialException, OSError) as e:
                self.get_logger().error(f'Serial error on {self.port}: {e}. Reopening')
                ser.close()
                ser = None
                continue

            if not chunk:
                if time.monotonic() - last_data > 5.0:
                    self.get_logger().warn(
                        f'No data from {self.port} for 5 s',
                        throttle_duration_sec=30.0)
                continue
            last_data = time.monotonic()

            buffer += chunk
            *lines, buffer = buffer.split(b'\n')
            if len(buffer) > 4096:
                buffer = b''  # no newline for too long, drop the junk
            for line in lines:
                self.handle_line(line)

        if ser is not None:
            ser.close()

    def handle_line(self, line):
        # The receiver also sends binary UBX, so lines can contain junk
        # before the '$'.
        fields = parse_sentence(line.decode('ascii', errors='ignore').strip())
        if fields is None:
            return

        kind = fields[0][2:]
        try:
            if kind == 'GGA':
                self.handle_gga(fields)
            elif kind == 'GSA':
                self.handle_gsa(fields)
        except (IndexError, ValueError) as e:
            self.get_logger().warn(
                f'Bad {fields[0]} sentence: {e}', throttle_duration_sec=10.0)

    def handle_gsa(self, fields):
        # $xxGSA,mode,fixtype,sv1..sv12,PDOP,HDOP,VDOP[,systemID]
        used = [sv for sv in fields[3:15] if sv]
        self.vdop = to_float(fields[17])
        if len(fields) > 18 and used:
            self.gsa_service |= SERVICE.get(int(fields[18]), 0)

    def handle_gga(self, fields):
        # $xxGGA,time,lat,N,lon,E,quality,numSV,HDOP,alt,M,sep,M,age,station
        quality = int(fields[6]) if fields[6] else 0

        msg = NavSatFix()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id
        msg.status.status = FIX_STATUS.get(quality, NavSatStatus.STATUS_NO_FIX)

        # Constellations used in the last full GSA set
        if self.gsa_service:
            self.service = self.gsa_service
        self.gsa_service = 0
        msg.status.service = self.service

        if quality == 0 or not fields[2] or not fields[4]:
            msg.latitude = msg.longitude = msg.altitude = float('nan')
            msg.position_covariance_type = NavSatFix.COVARIANCE_TYPE_UNKNOWN
        else:
            msg.latitude = nmea_to_degrees(fields[2], fields[3])
            msg.longitude = nmea_to_degrees(fields[4], fields[5])
            # Ellipsoid height = MSL altitude + geoid separation
            msg.altitude = to_float(fields[9]) + to_float(fields[11], 0.0)

            hdop = to_float(fields[8])
            vdop = self.vdop if not math.isnan(self.vdop) else 2.0 * hdop
            uere = UERE.get(quality, 4.0)
            msg.position_covariance[0] = (hdop * uere) ** 2
            msg.position_covariance[4] = (hdop * uere) ** 2
            msg.position_covariance[8] = (vdop * uere) ** 2
            msg.position_covariance_type = NavSatFix.COVARIANCE_TYPE_APPROXIMATED

        if quality != self.last_quality:
            sats = fields[7] or '0'
            if quality == 0:
                self.get_logger().info(f'No fix ({sats} satellites in use)')
            else:
                self.get_logger().info(f'Fix acquired: quality {quality}, {sats} satellites')
            self.last_quality = quality

        if rclpy.ok():
            self.fix_publisher.publish(msg)

    def stop(self):
        self.running = False
        self.thread.join(timeout=2.0)


def main(args=None):
    rclpy.init(args=args)
    gps = Go2GpsNode()

    try:
        rclpy.spin(gps)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        gps.stop()
        # On SIGINT/SIGTERM rclpy has already shut the context down, and
        # destroy_node() then raises on Humble, so only destroy while it's valid.
        if rclpy.ok():
            gps.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
