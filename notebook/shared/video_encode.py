import subprocess


def encode_video(audio_path: str, thumbnail_path: str, output_mp4: str) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", "30",
        "-i", thumbnail_path,
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "320k",
        "-pix_fmt", "yuv420p",
        "-shortest", "-movflags", "+faststart",
        output_mp4,
    ]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).returncode == 0