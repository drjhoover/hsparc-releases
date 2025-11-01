# hsparc/utils/frame_extractor.py
"""
Utility for extracting random frames from video files for recognition checks.
Uses OpenCV for reliable frame extraction.
"""
from __future__ import annotations

from pathlib import Path
from typing import List
import random

# Try OpenCV first
try:
    import cv2

    HAS_CV2 = True
    print("[frame_extractor] OpenCV available")
except ImportError:
    HAS_CV2 = False
    print("[frame_extractor] WARNING: OpenCV not available")
    print("[frame_extractor] Install with: pip install opencv-python")

# Import Qt components
try:
    from PySide6.QtGui import QImage, QPixmap
    from PySide6.QtMultimedia import QMediaPlayer, QVideoSink, QVideoFrame
    from PySide6.QtCore import QUrl, QEventLoop, QTimer

    HAS_QT = True
except ImportError as e:
    print(f"[frame_extractor] WARNING: Qt imports failed: {e}")
    HAS_QT = False
    QImage = None
    QPixmap = None


class SimpleFrameExtractor:
    """
    Simple interface for extracting video frames.
    Uses OpenCV if available, falls back to Qt.
    """

    @staticmethod
    def extract_frames_simple(video_path: str | Path, count: int = 6) -> List:
        """
        Extract frames using the best available method.

        Args:
            video_path: Path to video file
            count: Number of frames to extract (default 6)

        Returns:
            List of QPixmap objects containing the extracted frames
        """
        print(f"[frame_extractor] extract_frames_simple called for {video_path}")
        print(f"[frame_extractor] Requested frame count: {count}")
        print(f"[frame_extractor] HAS_CV2={HAS_CV2}, HAS_QT={HAS_QT}")

        if HAS_CV2:
            print("[frame_extractor] Using OpenCV method")
            return SimpleFrameExtractor._extract_with_opencv(video_path, count)
        elif HAS_QT:
            print("[frame_extractor] Using Qt fallback method")
            return SimpleFrameExtractor._extract_with_qt(video_path, count)
        else:
            print("[frame_extractor] ERROR: No extraction method available!")
            return []

    @staticmethod
    def _extract_with_opencv(video_path: str | Path, count: int) -> List:
        """Extract frames using OpenCV (recommended method)."""
        video_path = Path(video_path)
        if not video_path.exists():
            print(f"[frame_extractor] Video not found: {video_path}")
            return []

        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                print(f"[frame_extractor] Could not open video: {video_path}")
                return []

            # Get video properties
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            duration_ms = (total_frames / fps * 1000) if fps > 0 else 0

            print(f"[frame_extractor] Video: {total_frames} frames, {fps:.2f} fps, {duration_ms:.0f}ms")

            if total_frames < 10:
                print(f"[frame_extractor] Video too short: {total_frames} frames")
                cap.release()
                return []

            # Calculate frame positions based on requested count
            # Skip first and last 10% to avoid black frames/credits
            skip_start = int(total_frames * 0.10)
            skip_end = int(total_frames * 0.90)
            usable_frames = skip_end - skip_start

            if usable_frames < count:
                print(f"[frame_extractor] Warning: Not enough usable frames ({usable_frames}), using what's available")
                skip_start = max(10, int(total_frames * 0.05))
                skip_end = min(total_frames - 10, int(total_frames * 0.95))
                usable_frames = skip_end - skip_start

            # Generate evenly distributed positions
            if count == 6:
                # For 6 frames, use fixed positions for good coverage
                # 15%, 30%, 45%, 60%, 75%, 90% of the video
                frame_positions = [
                    int(total_frames * 0.15),
                    int(total_frames * 0.30),
                    int(total_frames * 0.45),
                    int(total_frames * 0.60),
                    int(total_frames * 0.75),
                    int(total_frames * 0.90)
                ]
            else:
                # For other counts, use evenly distributed positions
                step = usable_frames / (count + 1)
                frame_positions = [
                    skip_start + int(step * (i + 1))
                    for i in range(count)
                ]

            print(f"[frame_extractor] Extracting frames at positions: {frame_positions}")

            frames = []
            for frame_num in frame_positions:
                # Seek to frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)

                # Read frame
                ret, frame = cap.read()
                if not ret:
                    print(f"[frame_extractor] Failed to read frame {frame_num}")
                    continue

                # Check if frame is not completely black (indicates read failure)
                if frame.mean() < 1.0:
                    print(f"[frame_extractor] Frame {frame_num} appears to be black, skipping")
                    continue

                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Convert to QImage
                height, width, channels = frame_rgb.shape
                bytes_per_line = channels * width
                q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)

                # Convert to QPixmap - IMPORTANT: copy the data!
                pixmap = QPixmap.fromImage(q_image.copy())

                if not pixmap.isNull():
                    print(f"[frame_extractor] ✓ Extracted frame {frame_num}: {pixmap.width()}x{pixmap.height()}")
                    frames.append(pixmap)
                else:
                    print(f"[frame_extractor] ✗ Frame {frame_num} is null")

            cap.release()
            print(f"[frame_extractor] Total frames extracted: {len(frames)}/{count}")
            return frames

        except Exception as e:
            print(f"[frame_extractor] OpenCV extraction error: {e}")
            import traceback
            traceback.print_exc()
            return []

    @staticmethod
    def _extract_with_qt(video_path: str | Path, count: int) -> List:
        """Extract frames using Qt (fallback method - less reliable)."""
        if not HAS_QT:
            print("[frame_extractor] Qt components not available")
            return []

        video_path = Path(video_path)
        if not video_path.exists():
            print(f"[frame_extractor] Video not found: {video_path}")
            return []

        try:
            player = QMediaPlayer()
            sink = QVideoSink()
            player.setVideoSink(sink)

            frames = []
            current_frame = [None]

            def on_frame(frame):
                if frame.isValid():
                    image = frame.toImage()
                    if not image.isNull():
                        current_frame[0] = QPixmap.fromImage(image.copy())

            sink.videoFrameChanged.connect(on_frame)
            player.setSource(QUrl.fromLocalFile(str(video_path)))

            # Wait for duration
            loop = QEventLoop()
            duration_ms = [0]

            def on_duration(dur):
                duration_ms[0] = dur
                loop.quit()

            player.durationChanged.connect(on_duration)

            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            timeout.start(5000)

            loop.exec()

            if duration_ms[0] <= 0:
                print("[frame_extractor] Could not determine video duration")
                player.setSource(QUrl())
                return []

            # Calculate positions based on count
            if count == 6:
                # For 6 frames, use fixed positions
                positions = [
                    int(duration_ms[0] * 0.15),
                    int(duration_ms[0] * 0.30),
                    int(duration_ms[0] * 0.45),
                    int(duration_ms[0] * 0.60),
                    int(duration_ms[0] * 0.75),
                    int(duration_ms[0] * 0.90)
                ]
            else:
                # For other counts, use evenly distributed positions
                step = duration_ms[0] / (count + 1)
                positions = [int(step * (i + 1)) for i in range(count)]

            print(f"[frame_extractor] Seeking to positions: {positions}")

            for i, pos in enumerate(positions):
                current_frame[0] = None
                player.setPosition(pos)
                player.play()

                # Wait for frame
                loop2 = QEventLoop()
                timeout2 = QTimer()
                timeout2.setSingleShot(True)
                timeout2.timeout.connect(loop2.quit)
                timeout2.start(1500)

                loop2.exec()

                player.pause()

                if current_frame[0] and not current_frame[0].isNull():
                    frames.append(current_frame[0])
                    print(
                        f"[frame_extractor] ✓ Extracted frame {i + 1} at {pos}ms: {current_frame[0].width()}x{current_frame[0].height()}")
                else:
                    print(f"[frame_extractor] ✗ Failed to extract frame {i + 1} at {pos}ms")

            player.setSource(QUrl())
            print(f"[frame_extractor] Total frames extracted with Qt: {len(frames)}/{count}")
            return frames

        except Exception as e:
            print(f"[frame_extractor] Qt extraction error: {e}")
            import traceback
            traceback.print_exc()
            return []