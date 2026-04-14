import importlib
import threading
import numpy as np
from kivy.clock import Clock
from kivy.utils import platform


class AudioEngine:
    def __init__(self, sample_rate=44100, min_detect_freq=60, max_detect_freq=1200, noise_gate=0.008):
        self.sample_rate = sample_rate
        self.min_detect_freq = min_detect_freq
        self.max_detect_freq = max_detect_freq
        self.noise_gate = noise_gate
        self.stream = None
        self.sd = None
        self.backend = 'none'
        self.audio_enabled = False
        self.current_freq = 0.0
        self.smoothed_freq = 0.0
        self._missed_frames = 0
        self.max_missed_frames = 3
        self._stop_event = threading.Event()
        self._capture_thread = None
        self._jnius = None
        self._AudioRecord = None
        self._AudioFormat = None
        self._mic_audio_source = 1
        self._android_record = None
        self._load_audio_backend()

    def _post_status(self, on_status, message):
        Clock.schedule_once(lambda dt, msg=message: on_status(msg), 0)

    def _load_audio_backend(self):
        if platform == 'android':
            self.backend = 'android'
            return
        try:
            self.sd = importlib.import_module('sounddevice')
            self.backend = 'sounddevice'
        except Exception:
            self.sd = None
            self.backend = 'none'

    def request_permission_and_start(self, on_status):
        if platform != 'android':
            self.start(on_status)
            return
        try:
            android_permissions = importlib.import_module('android.permissions')
            Permission = android_permissions.Permission

            if android_permissions.check_permission(Permission.RECORD_AUDIO):
                self.start(on_status)
            else:
                def _callback(permissions, grants):
                    if grants and all(grants):
                        Clock.schedule_once(lambda dt: self.start(on_status), 0.1)
                    else:
                        self._post_status(on_status, 'Permission denied')

                android_permissions.request_permissions(
                    [Permission.RECORD_AUDIO],
                    _callback
                )
        except Exception:
            Clock.schedule_once(lambda dt: self.start(on_status), 0)

    def start(self, on_status):
        if self.backend == 'android':
            self._start_android(on_status)
        elif self.backend == 'sounddevice' and self.sd:
            try:
                self.stream = self.sd.InputStream(
                    callback=self.audio_callback,
                    channels=1,
                    samplerate=self.sample_rate,
                    blocksize=4096,
                    dtype='float32'
                )
                self.stream.start()
                self.audio_enabled = True
                self._post_status(on_status, 'Listening...')
            except Exception as e:
                self._post_status(on_status, f'Mic error: {e}')
        else:
            self._post_status(on_status, 'Backend unavailable')

    def _start_android(self, on_status):
        if self._android_record:
            return

        try:
            self._jnius = importlib.import_module('jnius')
            autoclass = self._jnius.autoclass
            self._AudioRecord = autoclass('android.media.AudioRecord')
            self._AudioFormat = autoclass('android.media.AudioFormat')
            try:
                media_recorder_audio_source = autoclass('android.media.MediaRecorder$AudioSource')
                self._mic_audio_source = int(media_recorder_audio_source.MIC)
            except Exception:
                # Fallback for devices/builds where the nested class is not exposed.
                self._mic_audio_source = 1
        except Exception as e:
            self._post_status(on_status, f'Jnius error: {e}')
            return

        try:
            channel_config = int(self._AudioFormat.CHANNEL_IN_MONO)
            audio_format = int(self._AudioFormat.ENCODING_PCM_16BIT)
            min_buffer = int(self._AudioRecord.getMinBufferSize(
                int(self.sample_rate), channel_config, audio_format
            ))
            buffer_size = max(min_buffer, 8192)

            self._android_record = self._AudioRecord(
                int(self._mic_audio_source),
                int(self.sample_rate),
                channel_config,
                audio_format,
                int(buffer_size)
            )

            if int(self._android_record.getState()) != int(self._AudioRecord.STATE_INITIALIZED):
                try:
                    self._android_record.release()
                except Exception:
                    pass
                self._android_record = None
                self._post_status(on_status, 'Android mic init failed')
                return

            self._android_record.startRecording()
            self._stop_event.clear()
            self.audio_enabled = True
            self._capture_thread = threading.Thread(
                target=self._android_capture_loop,
                args=(buffer_size,),
                daemon=True
            )
            self._capture_thread.start()
            self._post_status(on_status, 'Listening...')
        except Exception as e:
            self._post_status(on_status, f'Android failure: {e}')

    def _android_capture_loop(self, buffer_size):
        chunk_size = 4096
        try:
            while not self._stop_event.is_set() and self.audio_enabled:
                raw = bytearray(chunk_size)
                read_count = int(self._android_record.read(raw, 0, chunk_size))
                if read_count <= 0:
                    continue
                pcm = np.frombuffer(
                    raw[:read_count - (read_count % 2)],
                    dtype=np.int16
                ).astype(np.float32)
                detected_freq = self.detect_frequency_autocorr(pcm / 32768.0)
                if detected_freq > 0:
                    self._missed_frames = 0
                    self.smoothed_freq = (
                        detected_freq if self.smoothed_freq <= 0
                        else (self.smoothed_freq * 0.88 + detected_freq * 0.12)
                    )
                    self.current_freq = self.smoothed_freq
                else:
                    self._missed_frames += 1
                    if self._missed_frames <= self.max_missed_frames and self.current_freq > 0:
                        self.current_freq *= 0.995
                    else:
                        self.current_freq = 0.0
        finally:
            if self._jnius:
                try:
                    self._jnius.detach()
                except Exception:
                    pass

    def stop(self):
        self._stop_event.set()
        self.audio_enabled = False
        if self._android_record:
            try:
                self._android_record.stop()
                self._android_record.release()
            except Exception:
                pass
            self._android_record = None
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def detect_frequency_autocorr(self, data):
        signal = data - np.mean(data)
        if np.sqrt(np.mean(signal ** 2)) < self.noise_gate:
            return 0.0
        windowed = signal * np.hanning(len(signal))
        corr = np.correlate(windowed, windowed, mode='full')[len(signal) - 1:]
        min_lag = int(self.sample_rate / self.max_detect_freq)
        max_lag = int(self.sample_rate / self.min_detect_freq)
        d = np.diff(corr)
        start = max(min_lag, (np.where(d > 0)[0][0] + 1) if np.any(d > 0) else min_lag)
        if start >= max_lag or start >= len(corr):
            return 0.0
        peak = int(np.argmax(corr[start:max_lag]) + start)
        if peak <= 0 or peak + 1 >= len(corr):
            return 0.0
        if corr[peak] / corr[0] < 0.2:
            return 0.0
        y0, y1, y2 = corr[peak - 1], corr[peak], corr[peak + 1]
        denom = 2 * y1 - y0 - y2
        shift = 0.5 * (y2 - y0) / denom if abs(denom) > 1e-9 else 0
        return float(self.sample_rate / (peak + shift))

    def audio_callback(self, indata, frames, time, status):
        f = self.detect_frequency_autocorr(indata[:, 0])
        if f > 0:
            self._missed_frames = 0
            self.smoothed_freq = (
                f if self.smoothed_freq <= 0
                else (self.smoothed_freq * 0.88 + f * 0.12)
            )
            self.current_freq = self.smoothed_freq
        else:
            self._missed_frames += 1
            if self._missed_frames <= self.max_missed_frames and self.current_freq > 0:
                self.current_freq *= 0.995
            else:
                self.current_freq = 0.0