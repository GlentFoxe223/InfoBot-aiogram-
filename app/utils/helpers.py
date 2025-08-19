import re
from dotenv import load_dotenv
import yt_dlp
import os

class Player:
    def __init__(self, downloads='downloads'):
        self.downloads = downloads
        os.makedirs(self.downloads, exist_ok=True)

    def download(self, url):
        ydl_opts = {
            'outtmpl': os.path.join(self.downloads, '%(title).50s.%(ext)s'),
            'format': 'mp4',
            'quiet': True,
            'noplaylist': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename

    def delete(self, filepath):
        try:
            os.remove(filepath)
        except FileNotFoundError:
            pass

class Cleaner:
    def clean_words(self, page):
        load_dotenv(dotenv_path="/home/gleb/TGbot_projects/.env", override=True)

        bad_words = os.getenv('bad_words').split(',')

        for word in bad_words:
            word_pattern = r'\b' + re.escape(word) + r'\b'
            page = re.sub(word_pattern, '', page, flags=re.IGNORECASE)
        url_patterns = [
            r'в переводе [^ ]*\.org[^ ]*',
            r'В переводе [^ ]*\.org[^ ]*',
            r'https?://(?:www\.)?[^ ]*pic\.twitter\.com[^ ]*',
            r'https?://(?:www\.)?[^ ]*\.org[^ ]*',
            r'https?://(?:www\.)?[^ ]*\.ru[^ ]*',
            r'https?://(?:www\.)?[^ ]*\.com[^ ]*',
            r'https?://(?:www\.)?[^ ]*\.net[^ ]*',
            r'https?://(?:www\.)?[^ ]*\.info[^ ]*',
            r'https?://(?:www\.)?[^ ]*\.xyz[^ ]*',
            r'https?://(?:www\.)?[^ ]*t\.me[^ ]*',
            r'https?://(?:www\.)?[^ ]*youtu[^ ]*',
            r'https?://(?:www\.)?[^ ]*facebook\.com[^ ]*',
            r'https?://(?:www\.)?[^ ]*vk\.com[^ ]*',
            r'https?://(?:www\.)?[^ ]*instagram\.com[^ ]*',
            r'[^ ]*pic\.twitter\.com[^ ]*',
            r'[^ ]*\.org[^ ]*',
            r'[^ ]*\.ru[^ ]*',
            r'[^ ]*\.com[^ ]*',
            r'[^ ]*\.net[^ ]*',
            r'[^ ]*\.info[^ ]*',
            r'[^ ]*\.xyz[^ ]*',
            r'[^ ]*t\.me[^ ]*',
            r'[^ ]*youtu[^ ]*',
            r'[^ ]*facebook\.com[^ ]*',
            r'[^ ]*vk\.com[^ ]*',
            r'[^ ]*instagram\.com[^ ]*'
        ]

        for pattern in url_patterns:
            page = re.sub(pattern, '', page, flags=re.IGNORECASE)
        page = re.sub(r'[@#]\w+', '', page)
        clean_text = re.sub(r'\s+', ' ', page).strip()
        return clean_text