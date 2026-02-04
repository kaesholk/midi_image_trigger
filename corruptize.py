#!/usr/bin/env python3

import numpy as np
import tempfile

SAMPLE_RATE = 44100
_GLOBAL_BOARD = None

def init_worker():
    global _GLOBAL_BOARD
    if _GLOBAL_BOARD is None:
        from pedalboard._pedalboard import Pedalboard
        from pedalboard import Phaser, Delay, Reverb
        _GLOBAL_BOARD = Pedalboard([
            Delay(delay_seconds=1, feedback=0.8, mix=1),
            #Reverb(room_size=0.8, damping=0.5, wet_level=0.8, dry_level=0.2, width=1.0, freeze_mode=0.0),
            #Phaser(rate_hz=0.005, feedback=0.1, mix=1),
            #Gain(0),
        ])

def reduce(audio_data):
    from noisereduce import reduce_noise
    import numpy as _np
    import tempfile
    reduction = reduce_noise(y=audio_data, 
                            sr=SAMPLE_RATE, 
                            freq_mask_smooth_hz=87,
                            time_mask_smooth_ms=6,
                            thresh_n_mult_nonstationary=0.1,
                            sigmoid_slope_nonstationary=50,
                            n_fft=1024,
                            tmp_folder=tempfile.gettempdir())
    # residue = audio_data - reduction
    return reduction

def effect(audio_data, fs, frame_no, frame_count):
    global _GLOBAL_BOARD
    #audio_data = audio_data[::-1]
    audio_data = _GLOBAL_BOARD(audio_data, fs)
    #audio_data = reduce(audio_data)
    #audio_data = audio_data[::-1]
    return audio_data

def process_image_array(image_array, frame_no, total_frames):
    """
    Convert an image numpy array (H,W,3 uint8) to the 'audio' vector, run effect(), and return processed image array (H,W,3 uint8).
    """
    # Flatten and normalize to -1..1 (float32)
    audio_data = image_array.flatten().astype(np.float32, copy=False)
    minv = float(audio_data.min())
    maxv = float(audio_data.max())
    if maxv == minv:
        audio_data.fill(0.0)
    else:
        audio_data -= minv
        audio_data /= (maxv - minv)
        audio_data = 2.0 * audio_data - 1.0

    processed = effect(audio_data, SAMPLE_RATE, frame_no, total_frames)

    # Denormalize back to uint8 image bytes
    processed_bytes = ((processed + 1.0) * 0.5 * 255.0).clip(0, 255).astype(np.uint8)
    processed_img = processed_bytes.reshape(image_array.shape)
    return processed_img