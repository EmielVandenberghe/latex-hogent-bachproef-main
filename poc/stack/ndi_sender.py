#!/usr/bin/env python3
"""
NDI Test Stream Sender — Bachelorproef Mediaventures
Genereert SMPTE-kleurbalken en zendt ze als NDI-bron uit.
Vereist NDI SDK (libndi.so.5) + numpy.
Activeren: docker compose --profile demo up -d
"""
import ctypes
import ctypes.util
import time
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

NDI_SOURCE_NAME = os.environ.get('NDI_SOURCE_NAME', 'NDI Test Stream')
WIDTH = int(os.environ.get('NDI_WIDTH', '1280'))
HEIGHT = int(os.environ.get('NDI_HEIGHT', '720'))
FPS_N = int(os.environ.get('NDI_FPS_N', '25'))
FPS_D = int(os.environ.get('NDI_FPS_D', '1'))

# NDI FourCC BGRX = 'B' | ('G'<<8) | ('R'<<16) | ('X'<<24)
NDI_FOURCC_BGRX = 0x42 | (0x47 << 8) | (0x52 << 16) | (0x58 << 24)


class NDIlib_source_t(ctypes.Structure):
    _fields_ = [('p_ndi_name', ctypes.c_char_p),
                ('p_url_address', ctypes.c_char_p)]


class NDIlib_send_create_t(ctypes.Structure):
    _fields_ = [('p_ndi_name', ctypes.c_char_p),
                ('p_groups', ctypes.c_char_p),
                ('clock_video', ctypes.c_bool),
                ('clock_audio', ctypes.c_bool)]


class NDIlib_video_frame_v2_t(ctypes.Structure):
    _fields_ = [('xres', ctypes.c_int32),
                ('yres', ctypes.c_int32),
                ('FourCC', ctypes.c_int32),
                ('frame_rate_N', ctypes.c_int32),
                ('frame_rate_D', ctypes.c_int32),
                ('picture_aspect_ratio', ctypes.c_float),
                ('frame_format_type', ctypes.c_int32),
                ('timecode', ctypes.c_int64),
                ('p_data', ctypes.c_void_p),
                ('line_stride_in_bytes', ctypes.c_int32),
                ('p_metadata', ctypes.c_char_p),
                ('timestamp', ctypes.c_int64)]


def load_ndi_sdk():
    for name in ('libndi.so.6', 'libndi.so.5', 'libndi.so.4', 'libndi.so'):
        try:
            lib = ctypes.CDLL(name)
            lib.NDIlib_initialize.restype = ctypes.c_bool
            lib.NDIlib_initialize.argtypes = []

            lib.NDIlib_send_create.restype = ctypes.c_void_p
            lib.NDIlib_send_create.argtypes = [ctypes.POINTER(NDIlib_send_create_t)]

            lib.NDIlib_send_send_video_v2.restype = None
            lib.NDIlib_send_send_video_v2.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(NDIlib_video_frame_v2_t)]

            lib.NDIlib_send_destroy.restype = None
            lib.NDIlib_send_destroy.argtypes = [ctypes.c_void_p]

            lib.NDIlib_destroy.restype = None
            lib.NDIlib_destroy.argtypes = []

            return lib
        except OSError:
            continue
    return None


def make_color_bar_frame(width: int, height: int) -> bytes:
    """Genereer één BGRX kleurbalkenframe (SMPTE-kleuren)."""
    try:
        import numpy as np
        # (B, G, R, X) per balk
        colors = [
            (255, 255, 255, 255),  # Wit
            (0,   255, 255, 255),  # Geel
            (255, 255, 0,   255),  # Cyaan
            (0,   255, 0,   255),  # Groen
            (255, 0,   255, 255),  # Magenta
            (0,   0,   255, 255),  # Rood
            (255, 0,   0,   255),  # Blauw
            (0,   0,   0,   255),  # Zwart
        ]
        frame = np.zeros((height, width, 4), dtype=np.uint8)
        bw = width // len(colors)
        for i, c in enumerate(colors):
            x0 = i * bw
            x1 = (i + 1) * bw if i < len(colors) - 1 else width
            frame[:, x0:x1] = c
        return frame.tobytes()
    except ImportError:
        # Fallback zonder numpy: effen grijs frame
        log.warning('numpy niet beschikbaar — effen grijs testframe')
        return bytes([128, 128, 128, 255] * (width * height))


def main():
    lib = load_ndi_sdk()
    if lib is None:
        log.error('NDI SDK (libndi.so.5) niet gevonden — sender stopt.')
        return

    if not lib.NDIlib_initialize():
        log.error('NDIlib_initialize() mislukt')
        return

    cfg = NDIlib_send_create_t()
    cfg.p_ndi_name = NDI_SOURCE_NAME.encode()
    cfg.p_groups = None
    cfg.clock_video = True
    cfg.clock_audio = False

    send_inst = lib.NDIlib_send_create(ctypes.byref(cfg))
    if not send_inst:
        log.error('NDIlib_send_create mislukt')
        lib.NDIlib_destroy()
        return

    log.info('NDI-bron actief: "%s" — %dx%d @ %d/%d fps',
             NDI_SOURCE_NAME, WIDTH, HEIGHT, FPS_N, FPS_D)

    frame_data = make_color_bar_frame(WIDTH, HEIGHT)
    frame_bytes = (ctypes.c_uint8 * len(frame_data)).from_buffer_copy(frame_data)
    interval = FPS_D / FPS_N

    vf = NDIlib_video_frame_v2_t()
    vf.xres = WIDTH
    vf.yres = HEIGHT
    vf.FourCC = NDI_FOURCC_BGRX
    vf.frame_rate_N = FPS_N
    vf.frame_rate_D = FPS_D
    vf.picture_aspect_ratio = WIDTH / HEIGHT
    vf.frame_format_type = 1  # NDIlib_frame_format_type_progressive
    vf.p_data = ctypes.cast(frame_bytes, ctypes.c_void_p)
    vf.line_stride_in_bytes = WIDTH * 4
    vf.p_metadata = None

    try:
        while True:
            t0 = time.monotonic()
            lib.NDIlib_send_send_video_v2(send_inst, ctypes.byref(vf))
            elapsed = time.monotonic() - t0
            sleep = interval - elapsed
            if sleep > 0:
                time.sleep(sleep)
    except KeyboardInterrupt:
        pass
    finally:
        lib.NDIlib_send_destroy(send_inst)
        lib.NDIlib_destroy()
        log.info('NDI sender gestopt')


if __name__ == '__main__':
    main()
