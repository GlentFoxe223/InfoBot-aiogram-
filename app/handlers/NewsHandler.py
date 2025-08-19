from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os
import requests
from loguru import logger
from urllib.parse import urljoin, urlparse, parse_qs

class NewsHandler:
    def __init__(self):
        load_dotenv(dotenv_path="/home/gleb/TGbot_projects/.env", override=True)

        self.base_url = os.getenv('base_url')
        self.half_url = os.getenv('half_url')

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def fetch_page(self):
        try:
            response = requests.get(
                self.base_url,
                headers=self.headers,
                timeout=30,
                verify=False
            )
            if response.status_code == 200:
                logger.success("Страница успешно получена")
                return response.text
            else:
                logger.error(f"Ошибка загрузки страницы. Код ответа: {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.exception(f"Ошибка {e}")
        return None

    def parse_news(self, html):
        news_data = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            news_div = soup.find('div', class_='news news_latest')
            if news_div:
                ul_tag = news_div.find('ul')
                if ul_tag:
                    for li in ul_tag.find_all('li'):
                        link_tag = li.find('a', href=True)
                        if link_tag:
                            title = link_tag.get_text(strip=True)
                            url = link_tag['href']
                            img_tag=link_tag.find('div', class_="news__pic")
                            if img_tag:
                                image=img_tag.find('img', src=True)
                                image_link=image['src']
                                if title and url:
                                    news_data.append({'title': title, 'link': url, 'photo_link': image_link})
        except Exception as e:
            print(f"Ошибка парсинга новостей- {e}")
        return news_data

    def get_news(self):
        html = self.fetch_page()
        if html:
            return self.parse_news(html)
        return []
    
    def parse_deep_news(self, url):
        cleaned = []
        images = []
        media = []

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=30,
                verify=False
            )
            if response.status_code == 200:
                soup=BeautifulSoup(response.text, features='html.parser')
                if soup:
                    content_div=soup.find('div', class_='l-main')
                    if content_div:
                        content=content_div.find('article', class_='article')
                        if content:
                            try:
                                for p in content.find_all('p'):
                                    cleaned.append(self.clean_html_tags(p))
                            except:
                                print('Не найдены параграфы')

                            try:
                                main_photo_tag=content.find('figure', class_='article__left article__photo')
                                main_photo_url_tag=main_photo_tag.find('img', src=True)
                                main_image_url = main_photo_url_tag['src']
                                images.append(main_image_url)
                            except:
                                print('не найдено главное фото')

                            try:
                                for figure in content.find_all('figure'):
                                    photo_div = figure.find('div', class_='article__video-container')
                                    if photo_div:
                                        image_tag = photo_div.find('img', src=True)
                                        if image_tag:
                                            image_url = image_tag['src']
                                            images.append(image_url)
                            except:
                                print('не найдены доп фото')

                            try:
                                mediaextractor=ArticleVideoExtractor(response.text)
                                media=mediaextractor.extract_videos()
                            except:
                                print('не найдено медиа')
                                
                            deep_news = {
                                    'title': cleaned,
                                    'images': images,
                                    'media': media
                                    }

                        else:
                            print('не найден article')
                    else:
                        print('Не найден div с контентом')
                else:
                    print('Не удалось сформировать суп')
            else:
                print(f"Ошибка - Код ответа: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Ошибка - запроса: {e}")
        print(media)
        return deep_news
    
    def clean_html_tags(self, tag):
        allowed_tags = {'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'del', 'code', 'pre'}
        allowed_attrs = {'href'}
        for t in tag.find_all(True):
            if t.name not in allowed_tags:
                t.unwrap()
            else:
                t.attrs = {k: v for k, v in t.attrs.items() if k in allowed_attrs}
                if t.name == 'a' and 'href' not in t.attrs:
                    t.unwrap()
        return tag.decode_contents(formatter="html")    

    def get_deep_news(self, url):
        page = self.parse_deep_news(self.half_url+url)
        if page:
            return page
        else:
            return {'title':'Не удалось найти статью'}
        
class ArticleVideoExtractor:
    def __init__(self, html):
        self.soup = BeautifulSoup(html, 'html.parser')

    def _extract_youtube_id(self, url):
        parsed_url = urlparse(url)
        if parsed_url.hostname in ('www.youtube.com', 'youtube.com', 'youtu.be'):
            if parsed_url.path == '/watch':
                p = parse_qs(parsed_url.query)
                return p.get('v', [None])[0]
            elif parsed_url.hostname == 'youtu.be':
                return parsed_url.path[1:]
        return None

    def _extract_vimeo_id(self, url):
        parsed_url = urlparse(url)
        if parsed_url.hostname in ('vimeo.com', 'www.vimeo.com', 'player.vimeo.com'):
            path_parts = parsed_url.path.split('/')
            if 'video' in path_parts: 
                try:
                    return path_parts[path_parts.index('video') + 1]
                except (ValueError, IndexError):
                    pass
            elif len(path_parts) > 1 and path_parts[1].isdigit(): 
                return path_parts[1]
        return None

    def extract_videos(self):
        videos = []
        base_url = os.getenv('half_url')
        main_content_scope = self.soup.find('div', class_='main-wrap') or self.soup.find('article')
        search_scope = main_content_scope if main_content_scope else self.soup

        if main_content_scope:
            logger.info(f"Found main content scope ({main_content_scope.name}, class='{main_content_scope.get('class', [])}') for video extraction.")
        else:
            logger.warning("Could not find main content scope (main-wrap/article). Searching entire document for videos.")

        iframes = search_scope.find_all('iframe')
        logger.debug(f"Found {len(iframes)} potential <iframe> tags.")
        for i, iframe in enumerate(iframes):
            if 'src' in iframe.attrs and (iframe['src'].startswith('https://') or iframe['src'].startswith('http://')):
                src_url = iframe['src']
                videos.append(src_url)
                logger.debug(f"Extracted iframe video ({i+1}): {src_url}")
            else:
                logger.debug(f"Skipping iframe ({i+1}): No src or not http(s):// - {iframe.attrs.get('src')}")

        video_tags = search_scope.find_all('video')
        logger.debug(f"Found {len(video_tags)} potential <video> tags.")
        for i, video_tag in enumerate(video_tags):
            if 'src' in video_tag.attrs:
                src_url = video_tag['src']
                if not src_url.startswith('http'):
                    src_url = urljoin(base_url, src_url)
                videos.append(src_url)
                logger.debug(f"Extracted video from <video> tag src ({i+1}): {src_url}")
            
            sources = video_tag.find_all('source')
            logger.debug(f"Found {len(sources)} <source> tags within video tag ({i+1}).")
            for j, source in enumerate(sources):
                if 'src' in source.attrs:
                    src_url = source['src']
                    if not src_url.startswith('http'):
                        src_url = urljoin(base_url, src_url)
                    videos.append(src_url)
                    logger.debug(f"Extracted video from <source> tag ({i+1}.{j+1}): {src_url}")
                else:
                    logger.debug(f"Skipping source tag ({i+1}.{j+1}): No src - {source.attrs.get('src')}")

        video_containers = search_scope.find_all(['div', 'blockquote'], class_=[
            'video-main-container', 'video-inline-wrapper', 'player-video', 'b-player', 
            'js-video-player', 'video-block', 'embed-responsive', 'media-block',
            'twitter-tweet', 'instagram-media', 'tiktok-embed'
        ])
        logger.debug(f"Found {len(video_containers)} potential video container divs/blockquotes.")

        for k, container_tag in enumerate(video_containers):
            if 'data-src' in container_tag.attrs and (container_tag['data-src'].startswith('https://') or container_tag['data-src'].startswith('http://')):
                videos.append(container_tag['data-src'])
                logger.debug(f"Extracted video from data-src ({k+1}): {container_tag['data-src']}")
            
            if container_tag.name == 'blockquote' and 'cite' in container_tag.attrs:
                cite_url = container_tag['cite']
                if cite_url.startswith('https://') or cite_url.startswith('http://'):
                    if any(platform in cite_url for platform in [
                        'youtube.com', 'youtu.be', 'vimeo.com', 'tiktok.com', 
                        'facebook.com/watch', 'facebook.com/video', 'twitter.com', 'x.com', 'instagram.com'
                    ]):
                        videos.append(cite_url)
                        logger.debug(f"Extracted video from blockquote cite ({k+1}): {cite_url}")
                    else:
                        logger.debug(f"Skipping blockquote cite ({k+1}): Not a recognized video platform - {cite_url}")

            video_id = container_tag.get('data-video-id')
            player_type = container_tag.get('data-player-type')
            
            if video_id and player_type:
                if player_type.lower() == 'youtube':
                    youtube_url = f"https://www.youtube.com/watch?v={video_id}" 
                    videos.append(youtube_url)
                    logger.debug(f"Extracted YouTube video from data-attributes ({k+1}): {youtube_url}")
                elif player_type.lower() == 'vimeo':
                    vimeo_url = f"https://vimeo.com/{video_id}"
                    videos.append(vimeo_url)
                    logger.debug(f"Extracted Vimeo video from data-attributes ({k+1}): {vimeo_url}")
                elif player_type.lower() == 'tiktok':
                    tiktok_url = f"https://www.tiktok.com/embed/{video_id}" 
                    videos.append(tiktok_url)
                    logger.debug(f"Extracted TikTok video from data-attributes ({k+1}): {tiktok_url}")
                elif player_type.lower() == 'twitter' or player_type.lower() == 'x':
                    twitter_url = f"https://twitter.com/i/status/{video_id}"
                    videos.append(twitter_url)
                    logger.debug(f"Extracted Twitter/X video from data-attributes ({k+1}): {twitter_url}")
                elif player_type.lower() == 'instagram':
                    instagram_url = f"https://www.instagram.com/p/{video_id}/"
                    videos.append(instagram_url)
                    logger.debug(f"Extracted Instagram video from data-attributes ({k+1}): {instagram_url}")
                elif player_type.lower() == 'facebook':
                    facebook_url = f"https://www.facebook.com/watch/?v={video_id}"
                    videos.append(facebook_url)
                    logger.debug(f"Extracted Facebook video from data-attributes ({k+1}): {facebook_url}")
                else:
                    logger.debug(f"Unknown player type '{player_type}' for video ID '{video_id}' ({k+1}).")
            
            if 'data-player' in container_tag.attrs and (container_tag['data-player'].startswith('https://') or container_tag['data-player'].startswith('http://')):
                videos.append(container_tag['data-player'])
                logger.debug(f"Extracted video from data-player attribute ({k+1}): {container_tag['data-player']}")

            nested_iframe = container_tag.find('iframe', src=True)
            if nested_iframe and (nested_iframe['src'].startswith('https://') or nested_iframe['src'].startswith('http://')):
                src_url = nested_iframe['src']
                videos.append(src_url)
                logger.debug(f"Extracted nested iframe video from data-div/blockquote ({k+1}): {src_url}")

        unique_videos = list(set(videos))
        logger.info(f"Finished extracting videos. Found {len(unique_videos)} unique video URLs.")
        return unique_videos