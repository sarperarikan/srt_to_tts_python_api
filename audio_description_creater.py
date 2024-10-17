# -*- coding: utf-8 -*-

import wx
import os
import threading
import pyttsx3
import json
from datetime import timedelta
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_audioclips, CompositeAudioClip
import subprocess

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


def format_time(td):
    total_seconds = int(td.total_seconds())
    milliseconds = int(td.microseconds / 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def parse_srt_file(srt_path):
    with open(srt_path, 'r', encoding='utf-8') as f:
        srt_content = f.read()
    srt_blocks = list(filter(None, srt_content.split('\n\n')))
    captions = []
    for block in srt_blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            number = lines[0]
            time_range = lines[1]
            text_lines = lines[2:]
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
    engine.stop()  # Motoru kapat


def merge_audio_with_srt(video_path, srt_path, tts_volume=1.0, tts_rate=200, voice=None, output_format="mp4",
                         video_volume=1.0, log_callback=None, volume_intervals=None):
    captions = parse_srt_file(srt_path)
    tts_files = []

    if log_callback:
        log_callback(f"SRT dosyasında toplam {len(captions)} altyazı bulundu.")

    for index, entry in enumerate(captions):
        text = entry['text']
        audio_filename = os.path.join("conversion", f"temp_tts_{index}.wav")
        # TTS ses seviyesini burada varsayılan olarak ayarlıyoruz
        text_to_speech(text, audio_filename, 1.0, tts_rate, voice)
        tts_audio = AudioFileClip(audio_filename)
        tts_duration = tts_audio.duration
        tts_audio.close()
        tts_files.append({
            'file': audio_filename,
            'start': entry['start'].total_seconds(),
            'duration': tts_duration
        })
        if log_callback:
            log_callback(f"{index + 1}/{len(captions)}: '{text}' içeriği seslendirildi.")

    video = VideoFileClip(video_path)
    video_audio = video.audio

    # Video sürelerini al - Otomatik algılama
    video_duration = video.duration

    # Tüm zaman noktalarını topla
    times = set([0, video_duration])
    for tts in tts_files:
        times.add(tts['start'])
        times.add(tts['start'] + tts['duration'])
    if volume_intervals:
        for interval in volume_intervals:
            times.add(interval['start'])
            times.add(interval['end'])
    times = sorted(times)

    # Zaman aralıklarını oluştur ve ses seviyelerini belirle
    intervals = []
    for i in range(len(times) - 1):
        start = times[i]
        end = times[i + 1]
        # Varsayılan ses seviyelerini kullan
        tts_vol = tts_volume
        video_vol = video_volume
        if volume_intervals:
            for interval in volume_intervals:
                if interval['start'] <= start < interval['end']:
                    tts_vol = interval['tts_volume']
                    video_vol = interval['video_volume']
                    break
        intervals.append({
            'start': start,
            'end': end,
            'tts_volume': tts_vol,
            'video_volume': video_vol
        })

    # Video sesini parçalarına ayır ve ses seviyesini ayarla
    adjusted_video_audio_segments = []
    for interval in intervals:
        start = interval['start']
        end = interval['end']
        video_vol = interval['video_volume']
        segment = video_audio.subclip(start, end).volumex(video_vol)
        segment = segment.set_start(start)
        adjusted_video_audio_segments.append(segment)

    # TTS seslerini ayarla
    adjusted_tts_audio_clips = []
    tts_audio_clips = []  # TTS ses kliplerini saklamak için
    for tts in tts_files:
        tts_start = tts['start']
        tts_duration = tts['duration']
        tts_audio = AudioFileClip(tts['file'])
        tts_audio_clips.append(tts_audio)  # Kapatmak için saklıyoruz
        tts_end = tts_start + tts_duration
        for interval in intervals:
            interval_start = interval['start']
            interval_end = interval['end']
            tts_vol = interval['tts_volume']
            # Çakışma kontrolü
            overlap_start = max(tts_start, interval_start)
            overlap_end = min(tts_end, interval_end)
            if overlap_start < overlap_end:
                # Çakışma var
                tts_clip_start = overlap_start - tts_start
                tts_clip_end = overlap_end - tts_start
                if tts_clip_end > tts_duration:
                    tts_clip_end = tts_duration
                tts_clip = tts_audio.subclip(tts_clip_start, tts_clip_end)
                tts_clip = tts_clip.volumex(tts_vol)
                tts_clip = tts_clip.set_start(overlap_start)
                adjusted_tts_audio_clips.append(tts_clip)

    # Tüm sesleri birleştir
    all_audio_clips = adjusted_video_audio_segments + adjusted_tts_audio_clips
    final_audio = CompositeAudioClip(all_audio_clips)

    # Final videoyu oluştur
    final_video = video.set_audio(final_audio)

    video_output_path = os.path.join("conversion", f"final_output.{output_format}")

    # FFMPEG kullanarak videoyu kaydet
    if output_format == "mp4":
        final_video.write_videofile(video_output_path, codec='libx264', audio_codec='aac')
    elif output_format == "mp3":
        final_audio.fps = 44100  # Audio FPS ayarlanıyor
        final_audio.write_audiofile(video_output_path, codec='mp3')

    # Geçici TTS dosyalarını temizle
    for tts in tts_files:
        if os.path.exists(tts['file']):
            os.remove(tts['file'])

    # TTS ses kliplerini kapatın
    for tts_audio in tts_audio_clips:
        tts_audio.close()

    # Video ve final video kliplerini kapatın
    final_video.close()
    video.close()
    # final_audio.close()  # CompositeAudioClip'in close metodu yok

    if log_callback:
        log_callback(f"İşlem tamamlandı. Çıktı dosyası: {video_output_path}")

    return video_output_path


class IntervalDialog(wx.Dialog):
    def __init__(self, parent, default_start_time="", default_end_time="", *args, **kw):
        super(IntervalDialog, self).__init__(parent, *args, **kw)
        self.init_ui(default_start_time, default_end_time)

    def init_ui(self, default_start_time, default_end_time):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Start time
        start_time_sizer = wx.BoxSizer(wx.HORIZONTAL)
        start_time_label = wx.StaticText(self, label="Başlangıç Zamanı (ss:dd:ss,ms):")
        self.start_time_ctrl = wx.TextCtrl(self, value=default_start_time)
        start_time_sizer.Add(start_time_label, 0, wx.ALL | wx.CENTER, 5)
        start_time_sizer.Add(self.start_time_ctrl, 1, wx.ALL | wx.CENTER, 5)
        sizer.Add(start_time_sizer, 0, wx.EXPAND)

        # End time
        end_time_sizer = wx.BoxSizer(wx.HORIZONTAL)
        end_time_label = wx.StaticText(self, label="Bitiş Zamanı (ss:dd:ss,ms):")
        self.end_time_ctrl = wx.TextCtrl(self, value=default_end_time)
        end_time_sizer.Add(end_time_label, 0, wx.ALL | wx.CENTER, 5)
        end_time_sizer.Add(self.end_time_ctrl, 1, wx.ALL | wx.CENTER, 5)
        sizer.Add(end_time_sizer, 0, wx.EXPAND)

        # TTS Volume level
        tts_volume_sizer = wx.BoxSizer(wx.HORIZONTAL)
        tts_volume_label = wx.StaticText(self, label="TTS Ses Seviyesi (%):")
        self.tts_volume_ctrl = wx.SpinCtrl(self, min=0, max=200, initial=100)
        tts_volume_sizer.Add(tts_volume_label, 0, wx.ALL | wx.CENTER, 5)
        tts_volume_sizer.Add(self.tts_volume_ctrl, 1, wx.ALL | wx.CENTER, 5)
        sizer.Add(tts_volume_sizer, 0, wx.EXPAND)

        # Video Volume Adjustment
        video_volume_sizer = wx.BoxSizer(wx.HORIZONTAL)
        video_volume_label = wx.StaticText(self, label="Video Ses Seviyesi (%):")
        self.video_volume_ctrl = wx.SpinCtrl(self, min=0, max=200, initial=100)
        video_volume_sizer.Add(video_volume_label, 0, wx.ALL | wx.CENTER, 5)
        video_volume_sizer.Add(self.video_volume_ctrl, 1, wx.ALL | wx.CENTER, 5)
        sizer.Add(video_volume_sizer, 0, wx.EXPAND)

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(self, wx.ID_OK)
        cancel_btn = wx.Button(self, wx.ID_CANCEL)
        btn_sizer.Add(ok_btn)
        btn_sizer.Add(cancel_btn)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        self.SetSizer(sizer)
        sizer.Fit(self)


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
        self.tab4 = wx.Panel(notebook)

        notebook.AddPage(self.tab1, "Video ve SRT Seçimi")
        notebook.AddPage(self.tab2, "Zaman Aralığı Ayarları")
        notebook.AddPage(self.tab3, "TTS Ayarları")
        notebook.AddPage(self.tab4, "İşlem Detayları")

        self.init_tab1_ui()
        self.init_tab2_ui()
        self.init_tab3_ui()
        self.init_tab4_ui()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.EXPAND)
        panel.SetSizer(sizer)

        self.notebook = notebook

        self.SetSize((600, 500))
        self.SetTitle('Audio Description Content Creator v1.2.0')
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

        # Zaman Aralığı Ayarları
        self.intervalList = wx.ListCtrl(self.tab2, style=wx.LC_REPORT)
        self.intervalList.InsertColumn(0, 'Başlangıç Zamanı')
        self.intervalList.InsertColumn(1, 'Bitiş Zamanı')
        self.intervalList.InsertColumn(2, 'TTS Ses Seviyesi (%)')
        self.intervalList.InsertColumn(3, 'Video Ses Seviyesi (%)')
        self.intervalList.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_interval_right_click)
        sizer.Add(self.intervalList, 1, wx.EXPAND | wx.ALL, 5)

        # Düğmeler
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.addIntervalBtn = wx.Button(self.tab2, label="Yeni Aralık Ekle")
        self.removeIntervalBtn = wx.Button(self.tab2, label="Seçili Aralığı Sil")
        self.editIntervalBtn = wx.Button(self.tab2, label="Seçili Aralığı Düzenle")
        btn_sizer.Add(self.addIntervalBtn)
        btn_sizer.Add(self.removeIntervalBtn)
        btn_sizer.Add(self.editIntervalBtn)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER)

        self.addIntervalBtn.Bind(wx.EVT_BUTTON, self.on_add_interval)
        self.removeIntervalBtn.Bind(wx.EVT_BUTTON, self.on_remove_interval)
        self.editIntervalBtn.Bind(wx.EVT_BUTTON, self.on_edit_interval)

        self.tab2.SetSizer(sizer)

    def init_tab3_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.voiceLabel = wx.StaticText(self.tab3, label="Ses Seçimi:")
        sizer.Add(self.voiceLabel, 0, flag=wx.EXPAND)
        self.voiceComboBox = wx.ComboBox(self.tab3, choices=self.get_voice_names())
        sizer.Add(self.voiceComboBox, 0, flag=wx.EXPAND)

        self.ttsVolumeLabel = wx.StaticText(self.tab3, label="TTS Genel Ses Seviyesi (%):")
        sizer.Add(self.ttsVolumeLabel, 0, flag=wx.EXPAND)
        self.ttsVolumeSlider = wx.Slider(self.tab3, value=100, minValue=0, maxValue=200)
        sizer.Add(self.ttsVolumeSlider, 0, flag=wx.EXPAND)

        self.ttsRateLabel = wx.StaticText(self.tab3, label="TTS Konuşma Hızı:")
        sizer.Add(self.ttsRateLabel, 0, flag=wx.EXPAND)
        self.ttsRateSlider = wx.Slider(self.tab3, value=200, minValue=50, maxValue=400)
        sizer.Add(self.ttsRateSlider, 0, flag=wx.EXPAND)

        # Video varsayılan ses seviyesi
        self.videoVolumeLabel = wx.StaticText(self.tab3, label="Video Varsayılan Ses Seviyesi (%):")
        sizer.Add(self.videoVolumeLabel, 0, flag=wx.EXPAND)
        self.videoVolumeSlider = wx.Slider(self.tab3, value=100, minValue=0, maxValue=200)
        sizer.Add(self.videoVolumeSlider, 0, flag=wx.EXPAND)

        # Çıkış Formatı Seçimi
        self.outputFormatLabel = wx.StaticText(self.tab3, label="Çıkış Formatı:")
        sizer.Add(self.outputFormatLabel, 0, flag=wx.EXPAND)
        self.outputFormatComboBox = wx.ComboBox(self.tab3, choices=["mp4", "mp3"])
        sizer.Add(self.outputFormatComboBox, 0, flag=wx.EXPAND)

        # Ayarları Kaydet
        self.saveSettingsBtn = wx.Button(self.tab3, label="Ayarları Kaydet")
        self.saveSettingsBtn.Bind(wx.EVT_BUTTON, self.on_save_settings)
        sizer.Add(self.saveSettingsBtn, 0, flag=wx.EXPAND)

        # İşlemleri Başlat
        self.startBtn = wx.Button(self.tab3, label="Oluşturmaya Başla")
        self.startBtn.Bind(wx.EVT_BUTTON, self.on_start_processing)
        sizer.Add(self.startBtn, 0, flag=wx.EXPAND)

        self.tab3.SetSizer(sizer)

    def init_tab4_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.logTextCtrl = wx.TextCtrl(self.tab4, style=wx.TE_MULTILINE | wx.TE_READONLY)
        sizer.Add(self.logTextCtrl, 1, flag=wx.EXPAND)
        self.tab4.SetSizer(sizer)

    def load_previous_settings(self):
        settings = load_settings()
        if settings:
            self.voiceComboBox.SetValue(settings.get('voice', ''))
            self.outputFormatComboBox.SetValue(settings.get('output_format', 'mp4'))
            self.ttsVolumeSlider.SetValue(int(settings.get('tts_volume', 100)))
            self.ttsRateSlider.SetValue(int(settings.get('tts_rate', 200)))
            self.videoVolumeSlider.SetValue(int(settings.get('video_volume', 100)))

    def save_current_settings(self):
        settings = {
            'voice': self.voiceComboBox.GetValue(),
            'output_format': self.outputFormatComboBox.GetValue(),
            'tts_volume': self.ttsVolumeSlider.GetValue(),
            'tts_rate': self.ttsRateSlider.GetValue(),
            'video_volume': self.videoVolumeSlider.GetValue()
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

            # SRT dosyasını parse edip altyazıları saklayalım
            self.captions = parse_srt_file(self.srt_path)

    def on_choose_video(self, event):
        with wx.FileDialog(self, "Video dosyasını seçin", wildcard="MP4 files (*.mp4)|*.mp4",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            self.video_path = fileDialog.GetPath()
            self.videoPathText.SetLabel(f"Seçilen Video: {self.video_path}")

            # Video süresini alalım
            video = VideoFileClip(self.video_path)
            self.video_duration = video.duration
            video.close()

    def on_next_tab(self, event):
        self.notebook.SetSelection(1)

    def on_add_interval(self, event):
        """Zaman aralığı ekleme diyaloğunu aç."""
        # Varsayılan başlangıç ve bitiş zamanlarını belirleyelim
        if hasattr(self, 'captions') and self.captions:
            # İlk altyazının başlangıç ve son altyazının bitiş zamanlarını varsayılan olarak alalım
            default_start_time = format_time(self.captions[0]['start'])
            default_end_time = format_time(self.captions[-1]['end'])
        else:
            # Eğer SRT yoksa, 0 ve video süresini kullanabiliriz
            default_start_time = "00:00:00,000"
            default_end_time = format_time(timedelta(seconds=int(self.video_duration)))

        dlg = IntervalDialog(self, default_start_time, default_end_time)
        if dlg.ShowModal() == wx.ID_OK:
            start_time = dlg.start_time_ctrl.GetValue()
            end_time = dlg.end_time_ctrl.GetValue()
            tts_volume = dlg.tts_volume_ctrl.GetValue()
            video_volume = dlg.video_volume_ctrl.GetValue()

            # Zaman formatlarını doğrula
            try:
                parsed_start = parse_time(start_time)
                parsed_end = parse_time(end_time)
                if parsed_end <= parsed_start:
                    wx.MessageBox("Bitiş zamanı başlangıç zamanından sonra olmalı.", "Hata", wx.OK | wx.ICON_ERROR)
                    return
            except Exception as e:
                wx.MessageBox("Geçersiz zaman formatı. Lütfen ss:dd:ss,ms formatında girin.", "Hata",
                              wx.OK | wx.ICON_ERROR)
                return

            # Zaman aralıklarının çakışıp çakışmadığını kontrol et
            for i in range(self.intervalList.GetItemCount()):
                existing_start = parse_time(self.intervalList.GetItem(i, 0).GetText())
                existing_end = parse_time(self.intervalList.GetItem(i, 1).GetText())
                if not (parsed_end <= existing_start or parsed_start >= existing_end):
                    wx.MessageBox("Yeni zaman aralığı mevcut aralıklarla çakışıyor.", "Hata", wx.OK | wx.ICON_ERROR)
                    return

            # ListControl'e yeni zaman aralığını ekle
            index = self.intervalList.InsertItem(self.intervalList.GetItemCount(), start_time)
            self.intervalList.SetItem(index, 1, end_time)
            self.intervalList.SetItem(index, 2, str(tts_volume))
            self.intervalList.SetItem(index, 3, str(video_volume))
        dlg.Destroy()

    def on_edit_interval(self, event):
        """Seçili aralığı düzenleme diyaloğunu aç."""
        selected = self.intervalList.GetFirstSelected()
        if selected != -1:
            # Seçili satırdaki mevcut değerleri al
            start_time = self.intervalList.GetItem(selected, 0).GetText()
            end_time = self.intervalList.GetItem(selected, 1).GetText()
            tts_volume = self.intervalList.GetItem(selected, 2).GetText()
            video_volume = self.intervalList.GetItem(selected, 3).GetText()

            # Düzenleme penceresini aç
            dlg = IntervalDialog(self, start_time, end_time)
            dlg.start_time_ctrl.SetValue(start_time)
            dlg.end_time_ctrl.SetValue(end_time)
            dlg.tts_volume_ctrl.SetValue(int(tts_volume))
            dlg.video_volume_ctrl.SetValue(int(video_volume))

            if dlg.ShowModal() == wx.ID_OK:
                start_time = dlg.start_time_ctrl.GetValue()
                end_time = dlg.end_time_ctrl.GetValue()
                tts_volume = dlg.tts_volume_ctrl.GetValue()
                video_volume = dlg.video_volume_ctrl.GetValue()

                # Zaman formatlarını doğrula
                try:
                    parsed_start = parse_time(start_time)
                    parsed_end = parse_time(end_time)
                    if parsed_end <= parsed_start:
                        wx.MessageBox("Bitiş zamanı başlangıç zamanından sonra olmalı.", "Hata", wx.OK | wx.ICON_ERROR)
                        return
                except Exception as e:
                    wx.MessageBox("Geçersiz zaman formatı. Lütfen ss:dd:ss,ms formatında girin.", "Hata",
                                  wx.OK | wx.ICON_ERROR)
                    return

                # ListControl'deki mevcut aralığı güncelle
                self.intervalList.SetItem(selected, 0, start_time)
                self.intervalList.SetItem(selected, 1, end_time)
                self.intervalList.SetItem(selected, 2, str(tts_volume))
                self.intervalList.SetItem(selected, 3, str(video_volume))
            dlg.Destroy()
        else:
            wx.MessageBox("Lütfen düzenlemek istediğiniz aralığı seçin.", "Bilgi", wx.OK | wx.ICON_INFORMATION)

    def on_remove_interval(self, event):
        """Seçili aralığı sil."""
        selected = self.intervalList.GetFirstSelected()
        if selected != -1:
            if wx.MessageBox("Seçili aralığı silmek istediğinizden emin misiniz?", "Onay",
                             wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                self.intervalList.DeleteItem(selected)
        else:
            wx.MessageBox("Lütfen silmek istediğiniz aralığı seçin.", "Bilgi", wx.OK | wx.ICON_ERROR)

    def on_interval_right_click(self, event):
        """Seçili aralığı sağ tıkladığında menü oluştur."""
        menu = wx.Menu()
        delete_item = menu.Append(wx.ID_DELETE, "Sil")
        edit_item = menu.Append(wx.ID_EDIT, "Düzenle")
        self.Bind(wx.EVT_MENU, self.on_remove_interval, delete_item)
        self.Bind(wx.EVT_MENU, self.on_edit_interval, edit_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_save_settings(self, event):
        """Ayarları kaydet."""
        self.save_current_settings()
        wx.MessageBox("Ayarlar kaydedildi.", "Bilgi", wx.OK | wx.ICON_INFORMATION)

    def on_start_processing(self, event):
        self.notebook.SetSelection(3)
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
        tts_volume = self.ttsVolumeSlider.GetValue() / 100.0
        tts_rate = self.ttsRateSlider.GetValue()

        # Video varsayılan ses seviyesi
        video_volume = self.videoVolumeSlider.GetValue() / 100.0

        # Zaman aralıklarını al
        volume_intervals = []
        for i in range(self.intervalList.GetItemCount()):
            start_time = self.intervalList.GetItem(i, 0).GetText()
            end_time = self.intervalList.GetItem(i, 1).GetText()
            tts_volume_interval = int(self.intervalList.GetItem(i, 2).GetText()) / 100  # TTS ses seviyesi
            video_volume_interval = int(self.intervalList.GetItem(i, 3).GetText()) / 100  # Video ses seviyesi
            volume_intervals.append({
                'start': parse_time(start_time).total_seconds(),
                'end': parse_time(end_time).total_seconds(),
                'tts_volume': tts_volume_interval,
                'video_volume': video_volume_interval
            })

        self.log_message("SRT içeriği seçilen TTS ile seslendiriliyor...")
        self.log_message("Oluşturulan ses dosyaları videonun ilgili zamanlarına ekleniyor...")

        video_output_path = merge_audio_with_srt(
            self.video_path,
            self.srt_path,
            tts_volume,
            tts_rate,
            voice,
            output_format,
            video_volume,
            self.log_message,
            volume_intervals
        )

        self.log_message(f"İşlem tamamlandı. Çıktı dosyası: {video_output_path}")
        self.log_message("İşlemler başarıyla tamamlandı ve sesli betimlemeli içeriğiniz oluşturuldu.")

    def log_message(self, message):
        wx.CallAfter(self.logTextCtrl.AppendText, message + '\n')


if __name__ == '__main__':
    app = wx.App(False)
    frame = AppFrame(None)
    frame.Show(True)
    app.MainLoop()
