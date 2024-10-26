#!/usr/bin/env python3

import rospy
import cv2
import numpy as np
from sensor_msgs.msg import Image, CameraInfo
from cv_bridge import CvBridge
from visualization_msgs.msg import Marker
from tf.transformations import quaternion_from_euler, rotation_matrix, concatenate_matrices, euler_from_matrix

class ObjectTracker:
    def __init__(self):
        rospy.init_node('gazebo_recognition_node')
        
        self.bridge = CvBridge()
        
        self.camera_matrix = None
        self.image_width = None
        self.image_height = None
        self.got_camera_info = False
        
        self.marker_pub = rospy.Publisher('/detected_object', Marker, queue_size=10)        
        self.camera_info_sub = rospy.Subscriber('/camera_face/color/camera_info', 
                                              CameraInfo, 
                                              self.camera_info_callback)
        self.image_sub = None
        
        self.lower_green = np.array([40, 40, 40])
        self.upper_green = np.array([80, 255, 255])

        self.setup_transforms()

    def setup_transforms(self):
        """
        로봇 좌표계 (trunk frame):
        - X: 전방
        - Y: 좌측
        - Z: 상방
        
        카메라 좌표계 :
        - Z: 전방
        - X: 우측
        - Y: 하방
        """
        
        rot_x_pi = rotation_matrix(np.pi, [1, 0, 0])
        
        rot_x_minus_pi_2 = rotation_matrix(-np.pi/2, [1, 0, 0])
        rot_z_minus_pi_2 = rotation_matrix(-np.pi/2, [0, 0, 1])
        
        # 카메라의 Z축을 로봇의 X축과 정렬
        align_rot_y = rotation_matrix(-np.pi/2, [0, 1, 0])
        align_rot_z = rotation_matrix(np.pi, [0, 0, 1])
        align_rot = np.matmul(align_rot_z, align_rot_y)
        
        rot_mat = np.matmul(np.matmul(align_rot, rot_z_minus_pi_2), rot_x_minus_pi_2)
        
        # translation
        trans_mat = np.eye(4)
        trans_mat[0:3, 3] = [0.2785, 0.0125, 0.0167]
        
        self.transform_mat = np.matmul(trans_mat, rot_mat)
        self.inv_transform_mat = np.linalg.inv(self.transform_mat)

    def transform_point(self, point_camera):
        point_h = np.array([point_camera[0], point_camera[1], point_camera[2], 1.0])
        point_trunk = np.matmul(self.inv_transform_mat, point_h)
        
        return point_trunk[:3]

    def camera_info_callback(self, msg):
        if not self.got_camera_info:
            self.camera_matrix = np.array(msg.K).reshape(3, 3)
            self.fx = self.camera_matrix[0, 0]
            self.fy = self.camera_matrix[1, 1]
            self.cx = self.camera_matrix[0, 2]
            self.cy = self.camera_matrix[1, 2]
            
            self.image_width = msg.width
            self.image_height = msg.height
            
            self.got_camera_info = True
            
            self.image_sub = rospy.Subscriber('/camera_face/color/image_raw', 
                                            Image, 
                                            self.image_callback)
            
            self.camera_info_sub.unregister()

    def image_callback(self, msg):
        if not self.got_camera_info:
            return
            
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, "bgr8")
            
            # 이미지가 상하좌우 반전되어서 들어옴 
            cv_image = cv2.flip(cv_image, -1)  
            
            hsv = cv2.cvtColor(cv_image, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, self.lower_green, self.upper_green)
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if contours:
                largest_contour = max(contours, key=cv2.contourArea)
                x, y, w, h = cv2.boundingRect(largest_contour)
                
                center_x = x + w/2
                center_y = y + h/2
                
                cam_x = -((center_x - self.image_width/2) / self.fx) 
                cam_y = -((center_y - self.image_height/2) / self.fy) 
                
                depth = 1.0

                point_camera = [
                    depth,    
                    -cam_x * depth, 
                    -cam_y * depth  
                ]
                
                point_trunk = self.transform_point(point_camera)
                
                self.publish_marker(point_trunk)
                
                cv2.rectangle(cv_image, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.circle(cv_image, (int(center_x), int(center_y)), 5, (0, 0, 255), -1)

                cv2.imshow('Object Detection', cv_image)
                cv2.waitKey(1)
                
        except Exception as e:
            rospy.logerr(f"Error processing image: {str(e)}")

    def publish_marker(self, point_trunk):
        marker = Marker()
        marker.header.frame_id = "trunk"
        marker.header.stamp = rospy.Time.now()
        marker.type = Marker.ARROW
        marker.action = Marker.ADD
        
        marker.pose.position.x = 0
        marker.pose.position.y = 0
        marker.pose.position.z = 0
        
        dx = point_trunk[0]
        dy = point_trunk[1]
        dz = point_trunk[2]
        
        yaw = -np.arctan2(dy, dx)
        pitch = np.arctan2(dz, np.sqrt(dx*dx + dy*dy))
        q = quaternion_from_euler(0, pitch, yaw - np.pi/2)

        
        marker.pose.orientation.x = q[0]
        marker.pose.orientation.y = q[1]
        marker.pose.orientation.z = q[2]
        marker.pose.orientation.w = q[3]
        
        dist = np.sqrt(dx*dx + dy*dy + dz*dz)
        marker.scale.x = dist 
        marker.scale.y = 0.05 
        marker.scale.z = 0.05
        
        marker.color.r = 1.0
        marker.color.g = 0.0
        marker.color.b = 0.0
        marker.color.a = 1.0
        
        self.marker_pub.publish(marker)

if __name__ == '__main__':
    try:
        tracker = ObjectTracker()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass