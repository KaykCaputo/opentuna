import math
import os
import time
import numpy as np
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line, SmoothLine
from kivy.utils import platform
from src.audio_engine import AudioEngine

if platform != 'android':
    Window.size = (380, 680)

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


class TunerGauge(Widget):
    cents = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.draw, size=self.draw, cents=self.draw)

    def draw(self, *args):
        self.canvas.clear()
        with self.canvas:
            cx, cy = self.center
            radius = min(self.width, self.height) * 0.45
            dot_size = dp(16)

            Color(0.15, 0.15, 0.15, 1)
            SmoothLine(circle=(cx, cy, radius, -60, 60), width=dp(3))

            if abs(self.cents) < 3:
                Color(0.2, 0.8, 0.4, 1)
            else:
                Color(0.3, 0.3, 0.3, 1)
            Line(
                points=[
                    cx, cy + radius + dp(10),
                    cx - dp(6), cy + radius + dp(22),
                    cx + dp(6), cy + radius + dp(22)
                ],
                close=True,
                width=1.5
            )

            angle = 90 - (max(-50, min(50, self.cents)) * 1.2)
            rad = math.radians(angle)
            bx = cx + radius * math.cos(rad)
            by = cy + radius * math.sin(rad)

            if abs(self.cents) < 5:
                Color(0.1, 1, 0.5, 1)
            else:
                Color(0.8, 0.8, 0.8, 1)
            Ellipse(
                pos=(bx - dot_size / 2, by - dot_size / 2),
                size=(dot_size, dot_size)
            )


class StringButton(Widget):
    active = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.draw, size=self.draw, active=self.draw)

    def draw(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            if self.active:
                Color(1, 1, 1, 1)
            else:
                Color(0.15, 0.15, 0.15, 1)
            Ellipse(pos=self.pos, size=self.size)


class AppLayout(BoxLayout):
    current_note = StringProperty('--')
    display_note = StringProperty('--')
    display_accidental = StringProperty('')
    freq_text = StringProperty('Starting...')
    cents_text = StringProperty('-- cents')
    note_color = ListProperty([0.92, 0.92, 0.92, 1])
    cents_value = NumericProperty(0)
    gauge_size = NumericProperty(dp(250))
    note_font_sp = NumericProperty(80)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.audio_engine = AudioEngine()
        self.last_vibrate = 0
        self._signal_start_time = None
        self._smoothed_midi = None
        self._locked_midi = None
        self._pending_midi = None
        self._pending_count = 0
        self._last_detection_time = 0.0
        self.note_switch_hysteresis = 0.65
        self.note_confirm_frames = 4
        self.note_start_delay_seconds = 0.2
        self.note_hold_seconds = 0.8
        self.reset_after_silence_seconds = 2.0
        Clock.schedule_once(self.init_app, 0.5)
        Clock.schedule_interval(self.update_ui, 1 / 30)
        Window.bind(on_resize=self.recalculate_layout)

    def init_app(self, dt):
        self.recalculate_layout()
        self.audio_engine.request_permission_and_start(self.on_audio_status)

    def recalculate_layout(self, *args):
        if self.width < 100:
            return
        self.gauge_size = min(self.width * 0.7, self.height * 0.35)
        self.note_font_sp = self.height * 0.095

    def on_audio_status(self, msg):
        self.freq_text = msg

    def update_ui(self, dt):
        now = time.time()
        f = self.audio_engine.current_freq
        if f > 20:
            if (
                self._signal_start_time is None
                or (now - self._last_detection_time) > self.note_hold_seconds
            ):
                self._signal_start_time = now

            n_raw = 12 * np.log2(f / 440.0) + 69
            if self._smoothed_midi is None:
                self._smoothed_midi = n_raw
            else:
                self._smoothed_midi = self._smoothed_midi * 0.75 + n_raw * 0.25

            n = self._smoothed_midi
            target_nr = int(round(n))
            self._last_detection_time = now

            if self._locked_midi is None:
                self._locked_midi = target_nr
                self._pending_midi = None
                self._pending_count = 0
            elif abs(n - self._locked_midi) > self.note_switch_hysteresis:
                if self._pending_midi == target_nr:
                    self._pending_count += 1
                else:
                    self._pending_midi = target_nr
                    self._pending_count = 1

                if self._pending_count >= self.note_confirm_frames:
                    self._locked_midi = target_nr
                    self._pending_midi = None
                    self._pending_count = 0
            else:
                self._pending_midi = None
                self._pending_count = 0

            if now - self._signal_start_time < self.note_start_delay_seconds:
                self.current_note = '--'
                self.display_note = '--'
                self.display_accidental = ''
                self.note_color = [0.7, 0.7, 0.7, 1]
                self.cents_value *= 0.92
                self.cents_text = '-- cents'
                self.freq_text = 'Analyzing...'
                return

            nr = self._locked_midi if self._locked_midi is not None else target_nr
            self.current_note = NOTES[nr % 12]
            self.display_note = self.current_note[0]
            self.display_accidental = (
                self.current_note[1] if len(self.current_note) > 1 else ""
            )
            cents = int((n - nr) * 100)
            self.note_color = [0.2, 0.9, 0.45, 1] if abs(cents) < 3 else [0.92, 0.92, 0.92, 1]
            self.cents_value = self.cents_value * 0.7 + cents * 0.3
            self.cents_text = f"{cents:+} cents"
            self.freq_text = f"{f:.1f} Hz"
            if abs(cents) < 3 and now - self.last_vibrate > 1.5:
                self.vibrate()
        else:
            silence_for = now - self._last_detection_time
            if silence_for <= self.note_hold_seconds and self._locked_midi is not None:
                self.note_color = [0.7, 0.7, 0.7, 1]
                self.cents_value *= 0.95
                self.freq_text = 'Holding...'
            else:
                self.current_note = '--'
                self.display_note = '--'
                self.display_accidental = ''
                self.note_color = [0.7, 0.7, 0.7, 1]
                self.cents_value *= 0.9
                self.cents_text = '-- cents'
                self.freq_text = 'Listening...'

                if silence_for > self.reset_after_silence_seconds:
                    self._signal_start_time = None
                    self._smoothed_midi = None
                    self._locked_midi = None
                    self._pending_midi = None
                    self._pending_count = 0

    def vibrate(self):
        if platform == 'android':
            try:
                self.last_vibrate = time.time()
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                Context = autoclass('android.content.Context')
                BuildVersion = autoclass('android.os.Build$VERSION')
                BuildVersionCodes = autoclass('android.os.Build$VERSION_CODES')
                VibrationEffect = autoclass('android.os.VibrationEffect')

                activity = PythonActivity.mActivity
                vibrator = activity.getSystemService(Context.VIBRATOR_SERVICE)
                if not vibrator or not vibrator.hasVibrator():
                    return

                if int(BuildVersion.SDK_INT) >= int(BuildVersionCodes.O):
                    effect = VibrationEffect.createOneShot(
                        50,
                        VibrationEffect.DEFAULT_AMPLITUDE
                    )
                    vibrator.vibrate(effect)
                else:
                    vibrator.vibrate(50)
            except Exception:
                pass


class TunerApp(App):
    def build(self):
        Builder.load_file(os.path.join(os.path.dirname(__file__), 'app.kv'))
        return AppLayout()

    def on_pause(self):
        return True

    def on_resume(self):
        pass

    def on_stop(self):
        if hasattr(self.root, 'audio_engine'):
            self.root.audio_engine.stop()