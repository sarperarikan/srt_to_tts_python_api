# -*- coding: utf-8 -*-

import wx
import os
import threading
import pyttsx3
import json
from datetime import timedelta
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips

# "conversion" adlı bir dizin yoksa oluşturulur
if not os.path.exists('conversion'):
    os.makedirs('conversion')

# Ayarların kaydedileceği JSON dosyası
SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

def parse_time(time_str):
    hours, minutes, seconds_milliseconds = time_str.split(':')
    seconds, milliseconds = seconds_milliseconds.split(',')
    return timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds), milliseconds=int(milliseconds))

def parse_srt_file(srt_path):
    with open(srt_path, 'r', encoding='utf-8') as f:
        srt_content = f.read()
    srt_blocks = list(filter(None, srt_content.split('\n\n')))
    captions = []
    for block in srt_blocks:
        number, time_range, *text_lines = block.split('\n')
        start_time_str, _, end_time_str = time_range.split()
        start_time = parse_time(start_time_str)
        end_time = parse_time(end_time_str)
        captions.append({
            'start': start_time,
            'end': end_time,
            'text': ' '.join(text_lines)
        })
    return captions

def text_to_speech(text, filename, volume=1.0, rate=200, voice=None):
    engine = pyttsx3.init()
    if voice:
        engine.setProperty('voice', voice)
    engine.setProperty('volume', volume)
    engine.setProperty('rate', rate)
    engine.save_to_file(text, filename)
    engine.runAndWait()

def merge_audio_with_srt(video_path, srt_path, volume=1.0, rate=200, voice=None, output_format="mp4", video_volume=1.0, log_callback=None):
    captions = parse_srt_file(srt_path)
    tts_files = []

    if log_callback:
        log_callback(f"SRT dosyasında toplam {len(captions)} altyazı bulundu.")

    for index, entry in enumerate(captions):
        text = entry['text']
        audio_filename = os.path.join("conversion", f"temp_tts_{index}.wav")
        text_to_speech(text, audio_filename, volume, rate, voice)
        tts_files.append({
            'file': audio_filename,
            'start': entry['start'].total_seconds(),
            'end': entry['end'].total_seconds()
        })
        if log_callback:
            log_callback(f"{index + 1}/{len(captions)}: '{text}' içeriği seslendirildi.")

    if output_format == "mp4":
        video = VideoFileClip(video_path).volumex(video_volume)
        video_audio = video.audio
        tts_audios = []

        for tts in tts_files:
            tts_audio = AudioFileClip(tts['file']).set_start(tts['start'])
            tts_audios.append(tts_audio)

        final_audio = CompositeAudioClip([video_audio] + tts_audios)
        final_video = video.set_audio(final_audio)

        video_output_path = os.path.join("conversion", f"final_output.{output_format}")
        final_video.write_videofile(video_output_path, codec='libx264', audio_codec='aac')
    
    elif output_format == "mp3":
        video = VideoFileClip(video_path)
        video_audio = video.audio
        tts_audios = []

        for tts in tts_files:
            tts_audio = AudioFileClip(tts['file']).set_start(tts['start'])
            tts_audios.append(tts_audio)

        final_audio = CompositeAudioClip([video_audio] + tts_audios)
        final_audio.fps = 44100  # Audio FPS ayarlanıyor
        video_output_path = os.path.join("conversion", f"final_output.{output_format}")
        final_audio.write_audiofile(video_output_path, codec='mp3')

    for tts in tts_files:
        os.remove(tts['file'])

    if log_callback:
        log_callback(f"İşlem tamamlandı. Çıktı dosyası: {video_output_path}")

    return video_output_path

class AppFrame(wx.Frame):
    def __init__(self, *args, **kw):
        super(AppFrame, self).__init__(*args, **kw)
        self.engine = pyttsx3.init()
        self.init_ui()
        self.load_previous_settings()

    def init_ui(self):
        panel = wx.Panel(self)
        notebook = wx.Notebook(panel)

        self.tab1 = wx.Panel(notebook)
        self.tab2 = wx.Panel(notebook)
        self.tab3 = wx.Panel(notebook)

        notebook.AddPage(self.tab1, "Video ve SRT Seçimi")
        notebook.AddPage(self.tab2, "TTS ve Format Seçimi")
        notebook.AddPage(self.tab3, "İşlem Detayları")

        self.init_tab1_ui()
        self.init_tab2_ui()
        self.init_tab3_ui()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.EXPAND)
        panel.SetSizer(sizer)

        self.notebook = notebook

        self.SetSize((600, 400))
        self.SetTitle('Audio Description Content Creater v1.1.0')
        self.Centre()

    def init_tab1_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.chooseSrtBtn = wx.Button(self.tab1, label="SRT Seç")
        self.chooseSrtBtn.Bind(wx.EVT_BUTTON, self.on_choose_srt)
        sizer.Add(self.chooseSrtBtn, 0, flag=wx.EXPAND)
        self.srtPathText = wx.StaticText(self.tab1, label="Seçilen SRT: ")
        sizer.Add(self.srtPathText, 0, flag=wx.EXPAND)

        self.chooseVideoBtn = wx.Button(self.tab1, label="Video Seç (MP4)")
        self.chooseVideoBtn.Bind(wx.EVT_BUTTON, self.on_choose_video)
        sizer.Add(self.chooseVideoBtn, 0, flag=wx.EXPAND)
        self.videoPathText = wx.StaticText(self.tab1, label="Seçilen Video: ")
        sizer.Add(self.videoPathText, 0, flag=wx.EXPAND)

        self.nextBtn1 = wx.Button(self.tab1, label="Sonraki")
        self.nextBtn1.Bind(wx.EVT_BUTTON, self.on_next_tab)
        sizer.Add(self.nextBtn1, 0, flag=wx.EXPAND)

        self.tab1.SetSizer(sizer)

    def init_tab2_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.voiceLabel = wx.StaticText(self.tab2, label="Ses Seçimi:")
        sizer.Add(self.voiceLabel, 0, flag=wx.EXPAND)
        self.voiceComboBox = wx.ComboBox(self.tab2, choices=self.get_voice_names())
        sizer.Add(self.voiceComboBox, 0, flag=wx.EXPAND)

        self.outputFormatLabel = wx.StaticText(self.tab2, label="Çıkış Formatı:")
        sizer.Add(self.outputFormatLabel, 0, flag=wx.EXPAND)
        self.outputFormatComboBox = wx.ComboBox(self.tab2, choices=["mp4", "mp3"])
        sizer.Add(self.outputFormatComboBox, 0, flag=wx.EXPAND)

        self.videoVolumeLabel = wx.StaticText(self.tab2, label="Video Ses Seviyesi:")
        sizer.Add(self.videoVolumeLabel, 0, flag=wx.EXPAND)
        self.videoVolumeSlider = wx.Slider(self.tab2, value=100, minValue=0, maxValue=100)
        sizer.Add(self.videoVolumeSlider, 0, flag=wx.EXPAND)

        self.ttsVolumeLabel = wx.StaticText(self.tab2, label="TTS Ses Seviyesi:")
        sizer.Add(self.ttsVolumeLabel, 0, flag=wx.EXPAND)
        self.ttsVolumeSlider = wx.Slider(self.tab2, value=100, minValue=0, maxValue=100)
        sizer.Add(self.ttsVolumeSlider, 0, flag=wx.EXPAND)

        self.ttsRateLabel = wx.StaticText(self.tab2, label="TTS Konuşma Hızı:")
        sizer.Add(self.ttsRateLabel, 0, flag=wx.EXPAND)
        self.ttsRateSlider = wx.Slider(self.tab2, value=200, minValue=50, maxValue=400)
        sizer.Add(self.ttsRateSlider, 0, flag=wx.EXPAND)

        self.approveBtn = wx.Button(self.tab2, label="Seçimi Onayla")
        self.approveBtn.Bind(wx.EVT_BUTTON, self.on_approve_selection)
        sizer.Add(self.approveBtn, 0, flag=wx.EXPAND)

        self.startBtn = wx.Button(self.tab2, label="Oluşturmaya Başla")
        self.startBtn.Bind(wx.EVT_BUTTON, self.on_start_processing)
        sizer.Add(self.startBtn, 0, flag=wx.EXPAND)

        self.tab2.SetSizer(sizer)

    def init_tab3_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.logTextCtrl = wx.TextCtrl(self.tab3, style=wx.TE_MULTILINE | wx.TE_READONLY)
        sizer.Add(self.logTextCtrl, 1, flag=wx.EXPAND)
        self.tab3.SetSizer(sizer)

    def load_previous_settings(self):
        settings = load_settings()
        if settings:
            self.voiceComboBox.SetValue(settings.get('voice', ''))
            self.outputFormatComboBox.SetValue(settings.get('output_format', 'mp4'))
            self.videoVolumeSlider.SetValue(int(settings.get('video_volume', 100)))
            self.ttsVolumeSlider.SetValue(int(settings.get('tts_volume', 100)))
            self.ttsRateSlider.SetValue(int(settings.get('tts_rate', 200)))

    def save_current_settings(self):
        settings = {
            'voice': self.voiceComboBox.GetValue(),
            'output_format': self.outputFormatComboBox.GetValue(),
            'video_volume': self.videoVolumeSlider.GetValue(),
            'tts_volume': self.ttsVolumeSlider.GetValue(),
            'tts_rate': self.ttsRateSlider.GetValue()
        }
        save_settings(settings)

    def get_voice_names(self):
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        return [voice.name for voice in voices]

    def on_choose_srt(self, event):
        with wx.FileDialog(self, "SRT dosyasını seçin", wildcard="SRT files (*.srt)|*.srt",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            self.srt_path = fileDialog.GetPath()
            self.srtPathText.SetLabel(f"Seçilen SRT: {self.srt_path}")

    def on_choose_video(self, event):
        with wx.FileDialog(self, "Video dosyasını seçin", wildcard="MP4 files (*.mp4)|*.mp4",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            self.video_path = fileDialog.GetPath()
            self.videoPathText.SetLabel(f"Seçilen Video: {self.video_path}")

    def on_next_tab(self, event):
        self.notebook.SetSelection(1)

    def on_approve_selection(self, event):
        self.save_current_settings()
        wx.MessageBox("Seçim onaylandı.", "Bilgi", wx.OK | wx.ICON_INFORMATION)

    def on_start_processing(self, event):
        self.notebook.SetSelection(2)
        self.logTextCtrl.Clear()
        thread = threading.Thread(target=self.process_video)
        thread.start()

    def process_video(self):
        self.log_message("İşleme başlandı...")
        self.log_message("SRT dosyasındaki içerikler ayıklanıyor ve işleniyor...")

        if not hasattr(self, 'srt_path') or not hasattr(self, 'video_path'):
            self.log_message("Hata: SRT veya Video dosyası seçilmedi.")
            return

        voice_name = self.voiceComboBox.GetValue()
        voices = self.engine.getProperty('voices')
        voice = next((v.id for v in voices if v.name == voice_name), None)
        if not voice:
            self.log_message(f"Hata: Seçilen ses bulunamadı: {voice_name}")
            return

        output_format = self.outputFormatComboBox.GetValue()
        video_volume = self.videoVolumeSlider.GetValue() / 100.0
        tts_volume = self.ttsVolumeSlider.GetValue() / 100.0
        tts_rate = self.ttsRateSlider.GetValue()

        self.log_message("SRT içeriği seçilen TTS ile seslendiriliyor...")
        self.log_message("Oluşturulan ses dosyaları videonun ilgili zamanlarına ekleniyor...")

        video_output_path = merge_audio_with_srt(self.video_path, self.srt_path, tts_volume, tts_rate, voice, output_format, video_volume, self.log_message)
        self.log_message(f"İşlem tamamlandı. Çıktı dosyası: {video_output_path}")
        self.log_message("İşlemler başarıyla tamamlandı ve sesli betimlemeli içeriğiniz oluşturuldu.")

    def log_message(self, message):
        wx.CallAfter(self.logTextCtrl.AppendText, message + '\n')

if __name__ == '__main__':
    app = wx.App(False)
    frame = AppFrame(None)
    frame.Show(True)
    app.MainLoop()
