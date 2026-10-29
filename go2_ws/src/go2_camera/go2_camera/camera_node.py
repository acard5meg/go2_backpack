import threading

import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image
from cv_bridge import CvBridge


# The Go2 streams its front camera as H264 over RTP to a multicast group on
# the robot's wired network. Decoders: 'hw' uses the Jetson hardware decoder,
# 'sw' uses libav on the CPU.
DECODERS = {
    'hw': 'nvv4l2decoder ! nvvidconv ! video/x-raw,format=BGRx ! videoconvert',
    'sw': 'avdec_h264 ! videoconvert',
}


class Go2CameraFeedNode(Node):
    """
    Reads the Go2 front camera multicast stream and publishes it as
    go2_video_frames (sensor_msgs/Image) and go2_video_frames/compressed
    (sensor_msgs/CompressedImage, JPEG). Each topic is only converted and
    published while it has subscribers.
    """

    def __init__(self):
        super().__init__('go2_camera_feed')

        self.declare_parameter('multicast_address', '230.1.1.1')
        self.declare_parameter('port', 1720)
        self.declare_parameter('multicast_iface', 'enP8p1s0')
        self.declare_parameter('decoder', 'hw')
        self.declare_parameter('frame_id', 'Head_upper')
        self.declare_parameter('jpeg_quality', 80)

        address = self.get_parameter('multicast_address').value
        port = self.get_parameter('port').value
        iface = self.get_parameter('multicast_iface').value
        decoder = self.get_parameter('decoder').value
        self.frame_id = self.get_parameter('frame_id').value
        self.jpeg_params = [cv2.IMWRITE_JPEG_QUALITY,
                            self.get_parameter('jpeg_quality').value]

        self.raw_publisher = self.create_publisher(Image, 'go2_video_frames', 10)
        self.compressed_publisher = self.create_publisher(
            CompressedImage, 'go2_video_frames/compressed', 10)

        gstreamer_str = (
            f'udpsrc address={address} port={port} multicast-iface={iface} '
            '! application/x-rtp, media=video, encoding-name=H264 '
            f'! rtph264depay ! h264parse ! {DECODERS[decoder]} '
            '! video/x-raw,format=BGR ! appsink drop=1 max-buffers=1'
        )
        self.get_logger().info(f'Opening stream: {gstreamer_str}')
        self.cap = cv2.VideoCapture(gstreamer_str, cv2.CAP_GSTREAMER)
        if not self.cap.isOpened():
            raise RuntimeError('Could not open the Go2 video stream')

        # Used to convert between ROS and OpenCV images
        self.br = CvBridge()

        # cap.read() blocks until the next frame, so read in a thread rather
        # than polling from a timer (which drops frames).
        self.running = True
        self.thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.thread.start()

    def capture_loop(self):
        while self.running and rclpy.ok():
            ret, frame = self.cap.read()
            if not ret:
                continue

            want_raw = self.raw_publisher.get_subscription_count() > 0
            want_compressed = self.compressed_publisher.get_subscription_count() > 0
            if not (want_raw or want_compressed):
                continue

            stamp = self.get_clock().now().to_msg()

            if want_raw:
                msg = self.br.cv2_to_imgmsg(frame, encoding='bgr8')
                msg.header.stamp = stamp
                msg.header.frame_id = self.frame_id
                self.raw_publisher.publish(msg)

            if want_compressed:
                ok, jpeg = cv2.imencode('.jpg', frame, self.jpeg_params)
                if ok:
                    msg = CompressedImage()
                    msg.header.stamp = stamp
                    msg.header.frame_id = self.frame_id
                    msg.format = 'bgr8; jpeg compressed bgr8'
                    msg.data = jpeg.tobytes()
                    self.compressed_publisher.publish(msg)

    def destroy_node(self):
        self.running = False
        self.thread.join(timeout=1.0)
        self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    image_publisher = Go2CameraFeedNode()

    try:
        rclpy.spin(image_publisher)
    except KeyboardInterrupt:
        pass
    finally:
        image_publisher.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
