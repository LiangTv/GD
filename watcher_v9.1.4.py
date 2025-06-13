# -*- coding: utf-8 -*-
import os
import time
import xml.etree.ElementTree as ET
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, DirCreatedEvent
import logging
import subprocess
import datetime
import threading
from collections import defaultdict
from itertools import groupby
import json
# import re # escape_html 函數中未使用 re

# --- 設定 ---
MONITORED_DIRECTORIES = [
    "H:\\共用雲端硬碟\\@LiangTsaoEmby_本月更新\\電影",
    "H:\\共用雲端硬碟\\@LiangTsaoEmby_本月更新\\連載中",
    "H:\\共用雲端硬碟\\LiangTsaoEBooks\\《雜誌》",
    "H:\\共用雲端硬碟\\@LiangTsaoEmby_本月更新\\全集",
    "H:\\共用雲端硬碟\\LiangTsaoEmbyAnimation"
]
POLLING_INTERVAL_SECONDS = 300 
TARGET_EXTENSIONS = ('.mkv', '.mp4', '.pdf') 
OUTPUT_HTML_FILE = 'index.html'
ARCHIVE_HTML_FILE = 'archive.html' 
ARCHIVE_JS_FILE = 'archive_script.js' 
UPDATES_JSON_FILE = 'media_updates.json'
ITEMS_PER_PAGE = 30 
GIT_ACTION_DELAY_SECONDS = 15
DEFAULT_CATEGORY = 'tvshow'
MAX_ITEMS_ON_INDEX_PAGE = 5000
POLLING_BATCH_SAVE_COUNT = 50

# --- 全域變數與初始化 ---
git_timer = None
# last_poll_time 初始化放在主程式區塊
git_update_triggered = False 
REPO_PATH = os.path.dirname(os.path.abspath(__file__))
log_directory = os.path.join(REPO_PATH, 'GDLogs')
if not os.path.exists(log_directory): os.makedirs(log_directory)
log_file = os.path.join(log_directory, 'file_watcher.log')
logging.basicConfig(filename=log_file, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    encoding='utf-8', force=True)

# --- 持久化函數 ---
def load_updates(filename=UPDATES_JSON_FILE):
    filepath = os.path.join(REPO_PATH, filename)
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
            loaded_updates = []
            for item in data:
                try:
                    update_item = {
                        'timestamp': datetime.datetime.fromisoformat(item.get('timestamp', datetime.datetime.min.isoformat())),
                        'category': item.get('category', 'unknown'), 'filename': item.get('filename', 'N/A'),
                        'absolute_path': item.get('absolute_path', ''), 'relative_path': item.get('relative_path', 'N/A'),
                        'tmdb_id': item.get('tmdb_id', None), 'tmdb_url': item.get('tmdb_url', None),
                        'plot': item.get('plot', None) }
                    loaded_updates.append(update_item)
                except (ValueError, TypeError) as item_e: logging.warning(f"載入單筆紀錄時出錯，已跳過: {item}. 錯誤: {item_e}")
            logging.info(f"成功從 {filename} 載入 {len(loaded_updates)} 筆有效更新紀錄。")
            loaded_updates.sort(key=lambda x: x.get('timestamp', datetime.datetime.min), reverse=True)
            return loaded_updates
        else: logging.info(f"{filename} 不存在，將創建新的更新列表。"); return []
    except (json.JSONDecodeError, OSError) as e: logging.error(f"從 {filename} 載入更新紀錄失敗: {e}。將使用空的列表。"); return []
    except Exception as e_generic: logging.error(f"從 {filename} 載入時發生未預期錯誤: {e_generic}。將使用空的列表。"); return []

def save_updates(updates, filename=UPDATES_JSON_FILE):
    global processed_paths_set 
    filepath = os.path.join(REPO_PATH, filename)
    try:
        data_to_save = []
        current_updates_sorted = sorted(updates, key=lambda x: x.get('timestamp', datetime.datetime.min), reverse=True)
        new_processed_paths_this_save = set() 
        for item in current_updates_sorted:
            try:
                item_copy = item.copy()
                if isinstance(item_copy.get('timestamp'), datetime.datetime): item_copy['timestamp'] = item['timestamp'].isoformat()
                else: item_copy['timestamp'] = datetime.datetime.now().isoformat(); logging.warning(f"記錄缺少有效時間戳，已使用目前時間: {item.get('filename', 'N/A')}")
                data_to_save.append(item_copy)
                if item.get('absolute_path'): new_processed_paths_this_save.add(item.get('absolute_path').lower())
            except Exception as item_save_e: logging.warning(f"處理單筆紀錄儲存時出錯，已跳過: {item.get('filename', 'N/A')}. 錯誤: {item_save_e}")
        with open(filepath, 'w', encoding='utf-8') as f: json.dump(data_to_save, f, ensure_ascii=False, indent=4)
        logging.info(f"成功將 {len(data_to_save)} 筆更新紀錄儲存到 {filename}。")
        processed_paths_set = new_processed_paths_this_save
        logging.info(f"processed_paths_set 已基於儲存內容更新，包含 {len(processed_paths_set)} 條路徑。")
    except (TypeError, OSError) as e: logging.error(f"儲存更新紀錄到 {filename} 失敗: {e}")
    except Exception as e_generic: logging.error(f"儲存到 {filename} 時發生未預期錯誤: {e_generic}")

media_updates = load_updates()
processed_paths_set = set(item.get('absolute_path', '').lower() for item in media_updates if item.get('absolute_path'))

# --- NFO 解析函數 ---
def parse_nfo(nfo_path):
    logging.info(f"嘗試解析 NFO: {nfo_path}")
    if not os.path.exists(nfo_path): logging.warning(f"NFO 檔案不存在: {nfo_path}"); return None, None
    try:
        with open(nfo_path, 'r', encoding='utf-8') as f: content = f.read()
        tree = ET.fromstring(content); plot_element = tree.find('.//plot'); plot = plot_element.text if plot_element is not None else None; tmdb_id = None
        for uniqueid in tree.findall('.//uniqueid'):
            if uniqueid.get('type') == 'tmdb': tmdb_id = uniqueid.text; break
        logging.info(f"NFO 解析結果 - TMDb ID: {tmdb_id}, Plot: {'有' if plot else '無'}"); return tmdb_id, plot
    except ET.ParseError as e:
        logging.error(f"解析 NFO XML 時發生錯誤 ({nfo_path}): {e}")
        try:
            tmdb_id_tag = '<uniqueid type="tmdb">'; plot_tag_start = '<plot>'; plot_tag_end = '</plot>'; tmdb_id = None; plot = None; content_lower = content.lower()
            if tmdb_id_tag in content_lower:
                start_index = content_lower.find(tmdb_id_tag) + len(tmdb_id_tag); end_index = content.find('</uniqueid>', start_index)
                if end_index != -1: tmdb_id = content[start_index:end_index].strip()
            if plot_tag_start in content_lower:
                start_index = content_lower.find(plot_tag_start) + len(plot_tag_start); end_index = content.find(plot_tag_end, start_index)
                if end_index != -1: plot = content[start_index:end_index].strip()
            if tmdb_id or plot: logging.info(f"NFO 手動提取結果 - TMDb ID: {tmdb_id}, Plot: {'有' if plot else '無'}"); return tmdb_id, plot
            else: logging.warning(f"無法從非標準 XML NFO 中提取資訊: {nfo_path}"); return None, None
        except Exception as extract_e: logging.error(f"手動提取 NFO 資訊時發生錯誤 ({nfo_path}): {extract_e}"); return None, None
    except Exception as e: logging.error(f"讀取或解析 NFO 時發生未知錯誤 ({nfo_path}): {e}"); return None, None

def find_nfo_path(media_filepath):
    base_name = os.path.splitext(media_filepath)[0]; nfo_path = base_name + '.nfo'; parent_dir = os.path.dirname(media_filepath); grandparent_dir = os.path.dirname(parent_dir)
    if os.path.exists(nfo_path): logging.debug(f"找到同名 NFO: {nfo_path}"); return nfo_path, 'self'
    tvshow_nfo_path = os.path.join(parent_dir, 'tvshow.nfo')
    if os.path.exists(tvshow_nfo_path): logging.info(f"找到上層 tvshow.nfo: {tvshow_nfo_path}"); return tvshow_nfo_path, 'parent'
    if os.path.basename(parent_dir).lower().startswith('season'):
         tvshow_nfo_path_gp = os.path.join(grandparent_dir, 'tvshow.nfo')
         if os.path.exists(tvshow_nfo_path_gp): logging.info(f"找到上上層 tvshow.nfo: {tvshow_nfo_path_gp}"); return tvshow_nfo_path_gp, 'grandparent'
    logging.warning(f"找不到與 {media_filepath} 對應的 NFO 檔案"); return None, None

# --- HTML Escape 函數 ---
def escape_html(text):
    if not text: return ""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

# --- 核心處理邏輯函數 ---
def process_new_media(filepath, is_directory_event=False):
    item_name = os.path.basename(filepath)
    logging.debug(f"[{item_name}] (process_new_media) >> 開始處理 {'目錄' if is_directory_event else '檔案'}: {filepath}...")
    try:
        if is_directory_event:
            collection_base_path = "H:\\共用雲端硬碟\\@LiangTsaoEmby_本月更新\\全集"
            is_in_collection_dir = False
            try:
                 if os.path.abspath(filepath).lower().startswith(os.path.abspath(collection_base_path).lower()): is_in_collection_dir = True
            except Exception as path_e: logging.warning(f"[{item_name}] 判斷路徑歸屬時出錯: {path_e}")
            if not is_in_collection_dir: logging.debug(f"[{item_name}] (process_new_media) << 非 '全集' 目錄事件，忽略。"); return None
            logging.debug(f"[{item_name}] (process_new_media) >> 目錄在 '全集' 路徑下，等待 5 秒..."); time.sleep(5)
            nfo_path = os.path.join(filepath, 'tvshow.nfo'); tmdb_id, plot = None, None
            if os.path.exists(nfo_path): time.sleep(2); tmdb_id, plot = parse_nfo(nfo_path)
            else: logging.warning(f"[{item_name}] (process_new_media) >> 未找到 tvshow.nfo。")
            try: relative_path = os.path.relpath(filepath, collection_base_path)
            except ValueError: relative_path = item_name
            update_info = {'filename': item_name, 'absolute_path': filepath, 'relative_path': relative_path, 'timestamp': datetime.datetime.now(), 'category': 'collection', 'tmdb_id': tmdb_id, 'tmdb_url': f"https://www.themoviedb.org/tv/{tmdb_id}" if tmdb_id else None, 'plot': plot }
            logging.debug(f"[{item_name}] (process_new_media) << 目錄處理完成。"); return update_info
        elif os.path.isfile(filepath):
            if not item_name.lower().endswith(TARGET_EXTENSIONS): logging.debug(f"[{item_name}] (process_new_media) << 副檔名不符，忽略。"); return None
            logging.debug(f"[{item_name}] (process_new_media) >> 等待 5 秒..."); time.sleep(5)
            try: relative_path = os.path.relpath(filepath, "H:\\共用雲端硬碟")
            except ValueError: relative_path = filepath
            category = 'unknown'
            animation_base_path = "H:\\共用雲端硬碟\\LiangTsaoEmbyAnimation"; movie_base_path = "H:\\共用雲端硬碟\\@LiangTsaoEmby_本月更新\\電影"; tvshow_base_path = "H:\\共用雲端硬碟\\@LiangTsaoEmby_本月更新\\連載中"; magazine_base_path = "H:\\共用雲端硬碟\\LiangTsaoEBooks\\《雜誌》"; collection_base_path = "H:\\共用雲端硬碟\\@LiangTsaoEmby_本月更新\\全集"
            abs_filepath = os.path.abspath(filepath).lower()
            if abs_filepath.startswith(os.path.abspath(collection_base_path).lower()): logging.debug(f"[{item_name}] (process_new_media) << 在 '全集' 目錄下，忽略檔案。"); return None
            elif abs_filepath.startswith(os.path.abspath(animation_base_path).lower()) and item_name.lower().endswith(('.mkv', '.mp4')): category = 'animation'
            elif abs_filepath.startswith(os.path.abspath(movie_base_path).lower()) and item_name.lower().endswith(('.mkv', '.mp4')): category = 'movie'
            elif abs_filepath.startswith(os.path.abspath(tvshow_base_path).lower()) and item_name.lower().endswith(('.mkv', '.mp4')): category = 'tvshow'
            elif abs_filepath.startswith(os.path.abspath(magazine_base_path).lower()) and item_name.lower().endswith('.pdf'): category = 'magazine'
            if category == 'unknown': logging.warning(f"[{item_name}] (process_new_media) 無法根據路徑確定分類 ({filepath})，歸為未分類。")
            update_info = {'filename': item_name, 'absolute_path': filepath, 'relative_path': relative_path, 'timestamp': datetime.datetime.now(), 'category': category, 'tmdb_id': None, 'tmdb_url': None, 'plot': None }
            if category in ['movie', 'tvshow']:
                nfo_path, nfo_type = find_nfo_path(filepath)
                if nfo_path:
                    time.sleep(5); tmdb_id, plot = parse_nfo(nfo_path)
                    if not tmdb_id and nfo_type == 'self' and category == 'tvshow':
                        logging.info(f"[{item_name}] 本地 NFO ({nfo_path}) 缺少 TMDb ID，嘗試父級..."); parent_nfo_path, parent_nfo_type = find_nfo_path(os.path.dirname(filepath))
                        if parent_nfo_path and parent_nfo_type != 'self':
                             tmdb_id_parent, plot_parent = parse_nfo(parent_nfo_path)
                             if tmdb_id_parent: tmdb_id = tmdb_id_parent; plot = plot if plot else plot_parent; logging.info(f"[{item_name}] 從父級 NFO ({parent_nfo_path}) 獲取到 TMDb ID: {tmdb_id}")
                    if tmdb_id: update_info['tmdb_id'] = tmdb_id; update_info['tmdb_url'] = f"https://www.themoviedb.org/{'movie' if category == 'movie' else 'tv'}/{tmdb_id}"
                    if plot: update_info['plot'] = plot
            elif category == 'magazine': update_info['plot'] = "雜誌已更新。"
            elif category == 'animation': update_info['plot'] = "動漫已更新。"
            logging.debug(f"[{item_name}] (process_new_media) << 檔案處理完成。"); return update_info
        else: logging.warning(f"[{item_name}] (process_new_media) << 路徑既不是檔案也不是目錄，忽略。"); return None
    except Exception as e: logging.exception(f"[{item_name}] (process_new_media) !! 處理時發生未預期錯誤: {e}"); return None

# --- HTML 生成函數 ---
# --- HTML 生成函數 (V9.1.3 - 徹底移除錯誤註解，調整歷史連結位置) ---
# --- HTML 生成函數 (V9.1.4 - Tab 顯示最新日期) ---
def generate_html(all_updates_full_history):
    global MAX_ITEMS_ON_INDEX_PAGE, ARCHIVE_HTML_FILE, DEFAULT_CATEGORY # 確保引用
    updates_to_display = sorted(all_updates_full_history, key=lambda x: x.get('timestamp', datetime.datetime.min), reverse=True)[:MAX_ITEMS_ON_INDEX_PAGE]
    logging.info(f"將從 {len(all_updates_full_history)} 筆總記錄中，選取最新的 {len(updates_to_display)} 筆用於產生 index.html。")
    
    categorized_updates = defaultdict(list);
    for update in updates_to_display: # 注意：這裡使用的是 updates_to_display
        category = update.get('category', 'unknown')
        categorized_updates[category].append(update)

    # *** 修改開始：計算每個分類的最新更新日期 ***
    category_latest_dates = {}
    for category_key, items_in_category in categorized_updates.items():
        if items_in_category:
            # items_in_category 已經是按時間倒序的 (因為 updates_to_display 是)
            latest_item_timestamp = items_in_category[0].get('timestamp')
            if isinstance(latest_item_timestamp, datetime.datetime):
                category_latest_dates[category_key] = latest_item_timestamp.strftime('%m/%d') # 只顯示月/日
            else:
                category_latest_dates[category_key] = "N/A" # 時間戳格式不對
        else:
            category_latest_dates[category_key] = "--" # 此分類無項目
    # *** 修改結束 ***    

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'); items_per_page_val = ITEMS_PER_PAGE; default_category_val = DEFAULT_CATEGORY
    tab_buttons_html = ""; categories_order = [('tvshow', '劇集'), ('movie', '電影'), ('collection', '全集'), ('animation', '動漫'), ('magazine', '雜誌')]; available_categories = []
    default_category_has_content = bool(categorized_updates.get(default_category_val))

    for category_key, category_title in categories_order:
        has_content = bool(categorized_updates.get(category_key))
        if has_content: 
            is_active = "";
            if default_category_has_content:
                if category_key == default_category_val: is_active = "active"
            elif not available_categories: is_active = "active"
            
            # *** 修改開始：在 Tab 按鈕上加入最新日期 ***
            latest_date_str = category_latest_dates.get(category_key, "")
            button_text = category_title
            if latest_date_str and latest_date_str != "--" and latest_date_str != "N/A":
                button_text += f' <span class="tab-latest-date">({latest_date_str})</span>'
            # *** 修改結束 ***

            tab_buttons_html += f'        <button class="tab-button {is_active}" data-category="{category_key}">{button_text}</button>\n'; 
            available_categories.append(category_key)

    if categorized_updates.get('unknown'):
         is_active = "active" if 'unknown' == default_category_val and not default_category_has_content and not available_categories else ""
         # *** 修改開始：未知分類也嘗試顯示日期 ***
         latest_date_str_unknown = category_latest_dates.get('unknown', "")
         button_text_unknown = "未分類"
         if latest_date_str_unknown and latest_date_str_unknown != "--" and latest_date_str_unknown != "N/A":
             button_text_unknown += f' <span class="tab-latest-date">({latest_date_str_unknown})</span>'
         # *** 修改結束 ***
         tab_buttons_html += f'        <button class="tab-button {is_active}" data-category="unknown">{button_text_unknown}</button>\n'; 
         available_categories.append('unknown')
         
    tab_content_html = ""; processed_categories = categories_order + [('unknown', '未分類')]; found_updates_overall = False
    latest_date_overall = None
    if updates_to_display: latest_date_overall = max(u.get('timestamp', datetime.datetime.min) for u in updates_to_display).date()
    for category_key, _ in processed_categories:
        updates_in_category = categorized_updates.get(category_key, [])
        if not updates_in_category: continue
        found_updates_overall = True; is_active_pane = "";
        if default_category_has_content:
            if category_key == default_category_val: is_active_pane = "active"
        elif available_categories and category_key == available_categories[0]: is_active_pane = "active"
        pane_content = ""; month_groups = groupby(updates_in_category, key=lambda x: x.get('timestamp', datetime.datetime.min).strftime('%Y-%m')); has_content_in_pane = False
        for year_month, month_group in month_groups:
            month_items = list(month_group);
            if not month_items: continue
            try: month_dt = datetime.datetime.strptime(year_month + "-01", "%Y-%m-%d"); month_str = month_dt.strftime("%Y 年 %m 月")
            except ValueError: month_str = year_month
            pane_content += f'            <h3>{month_str}</h3>\n'
            day_groups = groupby(month_items, key=lambda x: x.get('timestamp', datetime.datetime.min).strftime('%Y-%m-%d'))
            for day, day_group in day_groups:
                day_items = list(day_group);
                if not day_items: continue
                day_dt = None
                try: day_dt = datetime.datetime.strptime(day, "%Y-%m-%d"); day_str = day_dt.strftime("%m 月 %d 日 (%A)")
                except ValueError: day_str = day
                has_content_in_pane = True
                is_latest_day_in_active_pane = is_active_pane == "active" and day_dt and day_dt.date() == latest_date_overall; day_group_classes = "day-group" + (" expanded" if is_latest_day_in_active_pane else ""); list_id = f"list-{category_key}-{day.replace('-', '')}"
                pane_content += f'            <div class="{day_group_classes}">\n'; pane_content += f'                <h4 class="day-header" data-target="#{list_id}"><span class="toggle-icon">{"+" if not is_latest_day_in_active_pane else "-"}</span> {day_str}</h4>\n'; list_visibility_class = "visible" if is_latest_day_in_active_pane else ""
                pane_content += f'                <ul class="update-list {list_visibility_class}" id="{list_id}" data-category="{category_key}">\n'
                item_counter_for_day = 0
                for item in day_items:
                    item_counter_for_day += 1; visibility_class = "hidden-item" if item_counter_for_day > items_per_page_val else ""
                    time_str = item.get('timestamp', datetime.datetime.min).strftime('%H:%M:%S'); plot_text = item.get('plot', '') or ''; escaped_plot = escape_html(plot_text); item_display_name = escape_html(item.get('filename', 'N/A')); relative_path_text = escape_html(item.get('relative_path', 'N/A')); tmdb_url_val = item.get('tmdb_url', '')
                    data_path_for_search = relative_path_text; data_filename_for_search = item_display_name if category_key == 'magazine' else ""
                    pane_content += f'                    <li class="update-item {visibility_class}" data-filename="{data_filename_for_search}" data-path="{data_path_for_search}" data-category="{category_key}">\n'; pane_content += '                       <div class="item-header">\n'; pane_content += f"                            <strong>{item_display_name}</strong>\n"; pane_content += f"                            <span class='item-time'>{time_str}</span>\n"; pane_content += '                       </div>\n'; pane_content += f"                        <div class='file-path'>{relative_path_text}</div>\n"
                    if tmdb_url_val: pane_content += f'                        <a href="{tmdb_url_val}" target="_blank" class="tmdb-link">TMDb 連結</a>\n'
                    if escaped_plot: pane_content += f"                        <blockquote>{escaped_plot}</blockquote>\n"; pane_content += "                    </li>\n"
                pane_content += '                </ul>\n'
                if item_counter_for_day > items_per_page_val: pane_content += f'                <button class="load-more-button day-pagination" data-target-list="#{list_id}" style="display: none;">顯示更多</button>\n'
                pane_content += '            </div>\n'
        if not has_content_in_pane: pane_content += "            <p>此分類目前沒有更新紀錄。</p>\n"
        tab_content_html += f'        <div class="content-pane {is_active_pane}" id="pane-{category_key}">\n{pane_content}        </div>\n'
    if not found_updates_overall: tab_content_html = "<p>目前沒有任何更新紀錄。</p>\n"
    
    # --- 組合完整的 HTML (f-string 版本 - 確保大括號正確) ---
    html_output = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>媒體更新列表 (最新 {MAX_ITEMS_ON_INDEX_PAGE} 筆)</title>
    <style> 
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; padding: 15px; background-color: #f8f9fa; color: #333; }} 
        .container {{ max-width: 1200px; margin: 0 auto; }} 
        h1 {{ text-align: center; color: #0056b3; margin-bottom: 10px; }} 
        .archive-link-container {{ text-align: center; margin-bottom: 20px; }} 
        .archive-link-container a {{ font-size: 1.1em; color: #17a2b8; text-decoration: none; padding: 8px 15px; border-radius: 4px; transition: background-color 0.2s ease, color 0.2s ease; }} 
        .archive-link-container a:hover {{ background-color: #17a2b8; color: white; text-decoration: none; }} 
        .search-container {{ margin-bottom: 20px; text-align: center; }} 
        #search-input {{ padding: 8px 12px; font-size: 1em; border: 1px solid #ccc; border-radius: 4px; width: 60%; max-width: 400px; transition: border-color 0.2s ease, box-shadow 0.2s ease; }} 
        #search-input:focus {{ border-color: #007bff; box-shadow: 0 0 0 2px rgba(0, 123, 255, 0.25); outline: none; }} 
        .tab-buttons {{ display: flex; justify-content: center; margin-bottom: 25px; border-bottom: 2px solid #dee2e6; flex-wrap: wrap; padding: 0 10px; }} 
        .tab-button {{ padding: 10px 15px; cursor: pointer; border: none; background-color: transparent; font-size: 1.05em; color: #007bff; margin: 0 3px 0px 3px; border-bottom: 3px solid transparent; transition: color 0.2s ease, border-color 0.2s ease; white-space: nowrap; }} 
        .tab-button:hover {{ color: #0056b3; }} 
        .tab-button.active {{ color: #0056b3; font-weight: bold; border-bottom-color: #0056b3; }} 
        /* *** 新增：Tab 上最新日期的樣式 *** */
        .tab-latest-date {{ font-size: 0.8em; color: #6c757d; margin-left: 5px; font-weight: normal; }}
        .tab-content {{ }} 
        .content-pane {{ display: none; animation: fadeIn 0.3s ease-in-out; }} 
        .content-pane.active {{ display: block; }} 
        @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }} 
        .day-group {{ margin-bottom: 15px; border: 1px solid #e9ecef; border-radius: 4px; background-color: #fff; overflow: hidden; }} 
        .day-header {{ background-color: #f1f3f5; color: #495057; padding: 10px 15px; margin: 0; cursor: pointer; font-weight: bold; display: flex; align-items: center; transition: background-color 0.2s ease; }} 
        .day-header:hover {{ background-color: #e9ecef; }} 
        .toggle-icon {{ display: inline-block; width: 1em; margin-right: 8px; text-align: center; font-weight: bold; }} 
        .update-list {{ list-style: none; padding: 0 15px 15px 15px; margin: 0; display: none; }} 
        .update-list.visible {{ display: block; }} 
        h3 {{ color: #17a2b8; margin-top: 20px; margin-bottom: 10px; border-left: 4px solid #17a2b8; padding-left: 10px; font-size: 1.3em; }} 
        li.update-item {{ margin-bottom: 10px; padding: 10px 12px; background-color: #fff; border: none; border-bottom: 1px solid #eee; border-radius: 0; box-shadow: none; transition: background-color 0.1s ease; }} 
        li.update-item:last-child {{ border-bottom: none; }} 
        .item-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }} 
        .item-header strong {{ font-size: 1.05em; color: #003975; margin-bottom: 0; flex-grow: 1; margin-right: 10px; word-break: break-all; }} 
        .item-time {{ font-size: 0.8em; color: #777; white-space: nowrap; }} 
        .file-path {{ font-family: 'Courier New', Courier, monospace; font-size: 0.8em; color: #666; margin-bottom: 6px; word-break: break-all; }} 
        blockquote {{ margin: 6px 0 6px 0px; padding: 6px 10px; border-left: 3px solid #007bff; background-color: #e9f5ff; color: #333; font-size: 0.85em; }} 
        a {{ color: #007bff; text-decoration: none; }} 
        a:hover {{ text-decoration: underline; }} 
        .tmdb-link {{ display: inline-block; margin-top: 4px; font-size: 0.85em; }} 
        .update-item.hidden-item {{ display: none; }} 
        .load-more-button.day-pagination {{ display: block; margin: 15px auto 5px auto; padding: 8px 16px; font-size: 0.9em; cursor: pointer; background-color: #28a745; color: white; border: none; border-radius: 4px; transition: background-color 0.2s ease; }} 
        .load-more-button.day-pagination:hover {{ background-color: #218838; }} 
        .highlight {{ background-color: yellow; font-weight: bold; }} 
        .update-item.search-hidden {{ display: none !important; }} 
        .day-group.search-hidden {{ display: none !important; }} 
        h3.search-hidden {{ display: none !important; }} 
        .search-active .load-more-button.day-pagination {{ display: none !important; }} 
        .footer-time {{ margin-top: 40px; text-align: center; font-size: 0.9em; color: #888; }} 
    </style>    
</head>
<body> <div class="container"> <h1>媒體更新總覽 (最新 {MAX_ITEMS_ON_INDEX_PAGE} 筆)</h1>
        <div class="archive-link-container">
            <a href="{ARCHIVE_HTML_FILE}" title="檢視所有歷史記錄並可進階搜尋">🔎 檢視完整歷史記錄</a>
        </div>
        <div class="search-container">
            <input type="search" id="search-input" placeholder="搜尋 劇集/電影/全集/動漫(依路徑) 或 雜誌(依檔名)...">
        </div> <div class="tab-buttons"> {tab_buttons_html} </div> <div class="tab-content"> {tab_content_html} </div> <p class="footer-time"><small>頁面最後生成時間: {now_str}</small></p>
    </div>
    <script>
        const tsMap = {{'剧':'劇','集':'集','电':'電','影':'影','杂':'雜','志':'誌','时':'時','间':'間','档':'檔','案':'案','更':'更','新':'新','列':'列','表':'表','签':'簽','标':'標','题':'題','内':'內','容':'容','搜':'搜','寻':'尋','显':'顯','示':'示','隐':'隱','藏':'藏','数':'數','据':'據','库': '庫','简':'簡','繁':'繁','体':'體','字':'字','转':'轉','换':'換','优':'優','化':'化','验':'驗','证':'證','权':'權','限':'限','设':'設','置':'置','错':'錯','误':'誤','讯':'訊','息':'息','系':'系','统':'統','环':'環','境':'境','版':'版','本':'本','处':'處','理':'理','回':'回','应': '應','网':'網','页':'頁','浏':'瀏','览':'覽','器':'器','缓':'緩','存':'存','清':'清','除':'除','模':'模','块':'塊','组':'組','织':'織','结':'結','构':'構','状':'狀','态':'態','负':'負','载':'載','压':'壓','力':'力','测':'測','试':'試','性':'性','能':'能','调':'調','优':'優','部':'部', '署':'署','迭':'疊','代':'代','开':'開','发':'發','周':'週','期':'期','计':'計','划':'劃','实':'實','现':'現','功':'功','能':'能','需':'需','求':'求','规':'規','范':'範','说':'說','明':'明','书':'書','用':'用','户':'戶','体':'體','验':'驗','界':'界','面':'面','计':'計','交互':'互動', '动':'動','画':'畫','视':'視','觉':'覺','元':'元','素':'素','图':'圖','标':'標','颜':'顏','色':'色','体':'體','排':'排','版':'版','布':'佈','局':'局','响':'響','应':'應','式':'式','适':'適','配':'配','不':'不','同':'同','备':'備','屏':'屏','幕':'幕','尺':'尺','寸':'寸','全':'全','漫':'漫', ' ': ' '}};
        const stMap = {{}}; for (const t in tsMap) {{ stMap[tsMap[t]] = t; }}
        function toSimp(t) {{ if(!t) return ""; let r=""; for(let i=0;i<t.length;i++) {{ r += stMap[t[i]]||t[i]; }} return r; }}
        function toTrad(t) {{ if(!t) return ""; let r=""; for(let i=0;i<t.length;i++) {{ r += tsMap[t[i]]||t[i]; }} return r; }}
        document.addEventListener('DOMContentLoaded', function() {{
            const itemsPerPage = {items_per_page_val};
            const tabButtons = document.querySelectorAll('.tab-button'); const contentPanes = document.querySelectorAll('.content-pane');
            const tabContainer = document.querySelector('.tab-buttons'); const searchInput = document.getElementById('search-input');
            const container = document.querySelector('.container'); const latestDateStr = "{latest_date_overall.isoformat() if latest_date_overall else ''}";
            if (tabContainer) {{ tabContainer.addEventListener('click', function(event) {{ if (event.target.classList.contains('tab-button')) {{
                const targetCategory = event.target.getAttribute('data-category'); tabButtons.forEach(button => {{ button.classList.remove('active'); }}); event.target.classList.add('active');
                contentPanes.forEach(pane => {{ pane.classList.toggle('active', pane.id === `pane-${{targetCategory}}`); }});
                filterItems(); resetAccordionState(targetCategory); updateAllPaginationButtonsVisibility(); }} }});
            }} else {{ console.error("Tab container not found!"); }}
            contentPanes.forEach(pane => {{ pane.addEventListener('click', function(event) {{
                const header = event.target.closest('.day-header');
                if (header && !event.target.closest('.load-more-button')) {{
                    const targetListId = header.getAttribute('data-target'); const targetList = pane.querySelector(targetListId);
                    const dayGroup = header.parentElement; const icon = header.querySelector('.toggle-icon');
                    if (targetList && dayGroup && icon) {{ dayGroup.classList.toggle('expanded'); targetList.classList.toggle('visible'); icon.textContent = dayGroup.classList.contains('expanded') ? '-' : '+'; }} }} }}); }});
             function setupDayPagination(listElement) {{ if (!listElement) return; const listId = listElement.id; const button = listElement.parentElement.querySelector(`.load-more-button.day-pagination[data-target-list="#${{listId}}"]`); if (!button) {{ return; }}
                 const allItemsInList = listElement.querySelectorAll('.update-item'); let visibleCount = 0;
                 allItemsInList.forEach(item => {{ if (!item.classList.contains('hidden-item') && !item.classList.contains('search-hidden')) {{ visibleCount++; }} }});
                 const totalVisibleItems = Array.from(allItemsInList).filter(item => !item.classList.contains('search-hidden')).length;
                 button.style.display = (totalVisibleItems > visibleCount && !container.classList.contains('search-active')) ? 'block' : 'none';
                 if (!button.dataset.listenerAttached) {{ button.addEventListener('click', function() {{ let newlyShown = 0; const hiddenItems = listElement.querySelectorAll('.update-item.hidden-item:not(.search-hidden)'); hiddenItems.forEach((item) => {{ if (newlyShown < itemsPerPage) {{ item.classList.remove('hidden-item'); newlyShown++; }} }}); if (listElement.querySelectorAll('.update-item.hidden-item:not(.search-hidden)').length === 0) {{ button.style.display = 'none'; }} }}); button.dataset.listenerAttached = 'true'; }} }}
            function updateAllPaginationButtonsVisibility() {{ document.querySelectorAll('ul.update-list').forEach(list => {{ setupDayPagination(list); const button = list.parentElement.querySelector(`.load-more-button.day-pagination[data-target-list="#${{list.id}}"]`); if (button && container.classList.contains('search-active')) {{ button.style.display = 'none'; }} }}); }}
            function filterItems() {{ const searchTerm = searchInput.value.toLowerCase().trim(); const activeTabButton = document.querySelector('.tab-button.active'); const activeCategory = activeTabButton ? activeTabButton.getAttribute('data-category') : null; container.classList.toggle('search-active', searchTerm !== ""); if (!activeCategory) return; const searchTrad = toTrad(searchTerm); const searchSimp = toSimp(searchTerm); let visibleMonths = new Set(); let visibleDays = new Set();
                document.querySelectorAll('.update-item').forEach(item => {{ const itemCategory = item.getAttribute('data-category'); let isMatch = false;
                    if (itemCategory === activeCategory) {{ if (searchTerm === "") {{ isMatch = true; }} else {{ const filename = item.getAttribute('data-filename').toLowerCase(); const path = item.getAttribute('data-path').toLowerCase(); let textToSearch = (itemCategory === 'magazine') ? filename : path; const targetTrad = toTrad(textToSearch); const targetSimp = toSimp(textToSearch); if ((targetTrad.includes(searchTrad) || targetTrad.includes(searchSimp)) || (targetSimp.includes(searchTrad) || targetSimp.includes(searchSimp))) {{ isMatch = true; }} }} }}
                    item.classList.toggle('search-hidden', !isMatch);
                    if (isMatch) {{ const dayGroup = item.closest('.day-group'); if (dayGroup) {{ visibleDays.add(dayGroup); const monthHeader = dayGroup.previousElementSibling; if (monthHeader && monthHeader.tagName === 'H3') {{ visibleMonths.add(monthHeader); }} if (!dayGroup.classList.contains('expanded')) {{ dayGroup.classList.add('expanded'); const list = dayGroup.querySelector('.update-list'); if (list) list.classList.add('visible'); const icon = dayGroup.querySelector('.toggle-icon'); if (icon) icon.textContent = '-'; }} }} }} }});
                document.querySelectorAll('.day-group').forEach(group => {{ const parentPane = group.closest('.content-pane'); if (parentPane && parentPane.id === `pane-${{activeCategory}}`) {{ group.classList.toggle('search-hidden', !visibleDays.has(group)); }} else if (!parentPane || !parentPane.classList.contains('active')) {{ group.classList.add('search-hidden'); }} }});
                 document.querySelectorAll('.tab-content h3').forEach(h3 => {{ const parentPane = h3.closest('.content-pane'); if (parentPane && parentPane.id === `pane-${{activeCategory}}`) {{ h3.classList.toggle('search-hidden', !visibleMonths.has(h3)); }} else if (!parentPane || !parentPane.classList.contains('active')) {{ h3.classList.add('search-hidden'); }} }});
                 if (searchTerm === "") {{ resetAccordionState(activeCategory); updateAllPaginationButtonsVisibility(); }} else {{ document.querySelectorAll('.load-more-button.day-pagination').forEach(btn => {{ btn.style.display = 'none'; }}); }} }}
            function resetAccordionState(activeCategory) {{ document.querySelectorAll('.day-group').forEach(group => {{ const parentPane = group.closest('.content-pane'); const dayHeader = group.querySelector('.day-header'); const list = group.querySelector('.update-list'); const icon = group.querySelector('.toggle-icon');
                if (parentPane && dayHeader && list && icon) {{ if(parentPane.id === `pane-${{activeCategory}}`) {{ const listId = list.id; const dateStrFromId = listId ? listId.split('-').pop() : null; const isLatestDay = latestDateStr && dateStrFromId && dateStrFromId === latestDateStr.replace(/-/g, ''); group.classList.toggle('expanded', isLatestDay); list.classList.toggle('visible', isLatestDay); icon.textContent = isLatestDay ? '-' : '+'; }} else {{ group.classList.remove('expanded'); list.classList.remove('visible'); icon.textContent = '+'; }} }} }}); }}
            if (searchInput) {{ searchInput.addEventListener('input', filterItems); }}
            updateAllPaginationButtonsVisibility(); const initialActiveTabButton = document.querySelector('.tab-button.active'); const initialActiveCategory = initialActiveTabButton ? initialActiveTabButton.getAttribute('data-category') : null; if(initialActiveCategory) {{ resetAccordionState(initialActiveCategory); }}
        }});
    </script>
</body>
</html>"""
    return html_output

# --- 產生 archive.html 的函數 ---
def generate_archive_html_shell():
    global ARCHIVE_JS_FILE, OUTPUT_HTML_FILE
    archive_html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>完整歷史媒體更新列表</title>
    <style> body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; padding: 15px; background-color: #f8f9fa; color: #333; }} .container {{ max-width: 1200px; margin: 0 auto; }} h1 {{ text-align: center; color: #0056b3; margin-bottom: 20px; }} .search-container {{ margin-bottom: 20px; text-align: center; }} #archive-search-input {{ padding: 8px 12px; font-size: 1em; border: 1px solid #ccc; border-radius: 4px; width: 60%; max-width: 400px; }} .archive-controls {{ margin-bottom: 20px; text-align: center; }} .archive-controls label {{ margin-right: 10px; }} .archive-controls select, .archive-controls input[type="number"] {{ padding: 6px; border-radius: 4px; border: 1px solid #ccc; margin-right: 15px;}} #loading-indicator {{ text-align: center; font-size: 1.2em; padding: 20px; display: none; }} #archive-results-container {{ margin-top: 20px; }} .pagination-controls {{ text-align: center; margin-top: 20px; }} .pagination-controls button {{ padding: 8px 15px; margin: 0 5px; cursor: pointer; background-color: #007bff; color:white; border:none; border-radius:4px; }} .pagination-controls button:disabled {{ background-color: #ccc; cursor: not-allowed; }} .pagination-info {{ margin: 0 15px; }} .tab-buttons {{ display: flex; justify-content: center; margin-bottom: 25px; border-bottom: 2px solid #dee2e6; flex-wrap: wrap; padding: 0 10px; }} .tab-button {{ padding: 10px 15px; cursor: pointer; border: none; background-color: transparent; font-size: 1.05em; color: #007bff; margin: 0 3px 0px 3px; border-bottom: 3px solid transparent; transition: color 0.2s ease, border-color 0.2s ease; white-space: nowrap; }} .tab-button:hover {{ color: #0056b3; }} .tab-button.active {{ color: #0056b3; font-weight: bold; border-bottom-color: #0056b3; }} .content-pane {{ display: none; animation: fadeIn 0.3s ease-in-out; }} .content-pane.active {{ display: block; }} @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }} .day-group {{ margin-bottom: 15px; border: 1px solid #e9ecef; border-radius: 4px; background-color: #fff; overflow: hidden; }} .day-header {{ background-color: #f1f3f5; color: #495057; padding: 10px 15px; margin: 0; cursor: pointer; font-weight: bold; display: flex; align-items: center; transition: background-color 0.2s ease; }} .day-header:hover {{ background-color: #e9ecef; }} .toggle-icon {{ display: inline-block; width: 1em; margin-right: 8px; text-align: center; font-weight: bold; }} .update-list {{ list-style: none; padding: 0 15px 15px 15px; margin: 0; display: none; }} .update-list.visible {{ display: block; }} h3 {{ color: #17a2b8; margin-top: 20px; margin-bottom: 10px; border-left: 4px solid #17a2b8; padding-left: 10px; font-size: 1.3em; }} li.update-item {{ margin-bottom: 10px; padding: 10px 12px; background-color: #fff; border: none; border-bottom: 1px solid #eee; border-radius: 0; box-shadow: none; transition: background-color 0.1s ease; }} li.update-item:last-child {{ border-bottom: none; }} .item-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }} .item-header strong {{ font-size: 1.05em; color: #003975; margin-bottom: 0; flex-grow: 1; margin-right: 10px; word-break: break-all; }} .item-time {{ font-size: 0.8em; color: #777; white-space: nowrap; }} .file-path {{ font-family: 'Courier New', Courier, monospace; font-size: 0.8em; color: #666; margin-bottom: 6px; word-break: break-all; }} blockquote {{ margin: 6px 0 6px 0px; padding: 6px 10px; border-left: 3px solid #007bff; background-color: #e9f5ff; color: #333; font-size: 0.85em; }} a {{ color: #007bff; text-decoration: none; }} a:hover {{ text-decoration: underline; }} .tmdb-link {{ display: inline-block; margin-top: 4px; font-size: 0.85em; }} .highlight {{ background-color: yellow; font-weight: bold; }} .footer-time {{ margin-top: 40px; text-align: center; font-size: 0.9em; color: #888; }} .no-results {{ text-align: center; padding: 20px; font-style: italic; color: #6c757d; }} </style>
    <script> const DEFAULT_CATEGORY = "{escape_html(DEFAULT_CATEGORY)}"; </script>
</head>
<body> <div class="container"> <h1>完整歷史媒體更新</h1> <div class="search-container"> <input type="search" id="archive-search-input" placeholder="搜尋歷史記錄 (可輸入繁/簡中文)..."> </div> <div class="archive-controls"> <label for="items-per-page-select">每頁顯示:</label> <select id="items-per-page-select"> <option value="30">30</option> <option value="50">50</option> <option value="100" selected>100</option> <option value="200">200</option> </select> <label for="goto-page-input">跳至頁碼:</label> <input type="number" id="goto-page-input" min="1" style="width: 60px;"> <button id="goto-page-btn">跳轉</button> </div> <div id="loading-indicator" style="display: none;">正在載入歷史記錄...</div> <div id="archive-results-container"> <div class="tab-buttons" id="archive-tab-buttons"></div> <div class="tab-content" id="archive-tab-content"> </div> </div> <div class="pagination-controls" id="archive-pagination-controls" style="display:none;"> <button id="prev-page">上一頁</button> <span id="page-info"></span> <button id="next-page">下一頁</button> </div> <p class="footer-time"><small><a href="{OUTPUT_HTML_FILE}">返回最新更新列表</a></small></p> </div> <script src="{ARCHIVE_JS_FILE}"></script> </body>
</html>"""
    return archive_html_content

# --- 延遲執行的函數 ---
def delayed_git_action():
    global media_updates, git_update_triggered, REPO_PATH, OUTPUT_HTML_FILE, ARCHIVE_HTML_FILE
    logging.info("觸發延遲 Git 操作 (delayed_git_action)...")
    main_html_generated = False
    archive_html_generated = False
    try:
        main_html_output = generate_html(media_updates)
        output_path_main = os.path.join(REPO_PATH, OUTPUT_HTML_FILE)
        with open(output_path_main, 'w', encoding='utf-8') as f: f.write(main_html_output)
        logging.info(f"已更新主頁 HTML 檔案: {output_path_main}")
        main_html_generated = True
    except Exception as e_html_main: logging.exception(f"產生主頁 index.html 時發生嚴重錯誤: {e_html_main}")
    try:
        archive_html_content = generate_archive_html_shell() 
        output_path_archive = os.path.join(REPO_PATH, ARCHIVE_HTML_FILE)
        with open(output_path_archive, 'w', encoding='utf-8') as f: f.write(archive_html_content)
        logging.info(f"已更新歷史記錄頁面 HTML 檔案: {output_path_archive}")
        archive_html_generated = True
    except Exception as e_html_archive: logging.exception(f"產生 archive.html 時發生嚴重錯誤: {e_html_archive}")
    if commit_and_push_changes(): logging.info("Git 推送完成。")
    else: logging.error("Git 推送失敗。")
    git_update_triggered = False

# --- Git 操作函數 ---
def commit_and_push_changes():
    global git_timer 
    logging.info("開始執行 Git 操作...")
    try:
        files_to_add = [OUTPUT_HTML_FILE, UPDATES_JSON_FILE]
        archive_html_path = os.path.join(REPO_PATH, ARCHIVE_HTML_FILE)
        archive_js_path = os.path.join(REPO_PATH, ARCHIVE_JS_FILE)
        if os.path.exists(archive_html_path): files_to_add.append(ARCHIVE_HTML_FILE)
        if os.path.exists(archive_js_path): files_to_add.append(ARCHIVE_JS_FILE)
        logging.info(f"執行: git add {' '.join(files_to_add)}")
        existing_files_to_add = [f for f in files_to_add if os.path.exists(os.path.join(REPO_PATH, f))]
        if not existing_files_to_add: logging.info("沒有找到任何需要 add 的檔案。"); # return True # 保持不 return，讓後續檢查 staged
        
        # 即使 existing_files_to_add 為空，也執行一次 add，以便清除已刪除檔案的追蹤
        subprocess.run(['git', 'add'] + existing_files_to_add + ["-u"], cwd=REPO_PATH, capture_output=True, text=True, check=False, encoding='utf-8') # -u for updating tracked files (deletions)

        commit_message = f"Automated update: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        logging.info(f"執行: git commit -m '{commit_message}'")
        
        # 檢查是否有實際變更需要提交 (staged changes)
        result_status_staged = subprocess.run(['git', 'diff', '--staged', '--quiet'], cwd=REPO_PATH, check=False) 
        
        if result_status_staged.returncode == 0: 
             logging.info(f"沒有偵測到任何已暫存的檔案變更，跳過 commit 和 push。")
             return True

        logging.debug(f"Git status output before commit (porcelain):\n{subprocess.run(['git', 'status', '--porcelain'], cwd=REPO_PATH, capture_output=True, text=True, encoding='utf-8').stdout}")
        result_commit = subprocess.run(['git', 'commit', '-m', commit_message], cwd=REPO_PATH, capture_output=True, text=True, check=True, encoding='utf-8')
        logging.info(f"Git commit 輸出:\n{result_commit.stdout}")
        logging.info("執行: git push origin main");
        result_push = subprocess.run(['git', 'push', 'origin', 'main'], cwd=REPO_PATH, capture_output=True, text=True, check=True, encoding='utf-8')
        logging.info(f"Git push 輸出:\n{result_push.stdout}")
        logging.info("Git 操作成功完成。"); return True
    except subprocess.CalledProcessError as e: logging.error(f"Git 操作失敗: {e}\n指令: {e.cmd}\n返回碼: {e.returncode}\n輸出: {e.stdout}\n錯誤: {e.stderr}"); return False
    except FileNotFoundError: logging.error("Git 指令未找到。請確保 Git 已安裝並在 PATH 中。"); return False
    except Exception as e: logging.error(f"執行 Git 操作時發生未知錯誤: {e}"); return False

# --- 文件監視器事件處理 與 輪詢輔助 ---
def trigger_update_process():
    global media_updates, git_update_triggered, git_timer
    logging.info(">>> trigger_update_process() 被調用")
    save_updates(media_updates) 
    if git_update_triggered: 
        if git_timer is not None and git_timer.is_alive():
            git_timer.cancel(); logging.info("取消了之前的延遲 Git 操作計時器 (因 trigger_update_process)。")
    logging.info(f"將在 {GIT_ACTION_DELAY_SECONDS} 秒後執行 Git HTML 生成與推送 (由 trigger_update_process 安排)...")
    git_timer = threading.Timer(GIT_ACTION_DELAY_SECONDS, delayed_git_action)
    git_timer.start(); git_update_triggered = True

class MyHandler(FileSystemEventHandler):
    def on_created(self, event):
        global media_updates, processed_paths_set
        filepath = event.src_path; abs_filepath_lower = os.path.abspath(filepath).lower()
        event_type_str = "目錄" if event.is_directory else "檔案"
        logging.info(f"---------- [Event Start] 偵測到新{event_type_str}: {filepath} ----------")
        try:
            if abs_filepath_lower in processed_paths_set: logging.warning(f"[{os.path.basename(filepath)}] (事件) 此路徑已在 processed_paths_set 中，忽略。"); return
            time.sleep(0.5)
            update_info = process_new_media(filepath, is_directory_event=event.is_directory)
            if update_info:
                if not any(item.get('absolute_path', '').lower() == abs_filepath_lower for item in media_updates):
                    media_updates.append(update_info); processed_paths_set.add(abs_filepath_lower) 
                    media_updates.sort(key=lambda x: x.get('timestamp', datetime.datetime.min), reverse=True)
                    logging.info(f"新增更新記錄 (來自事件 - 分類: {update_info['category']}): {update_info['filename']}")
                    trigger_update_process() 
                else: logging.warning(f"[{update_info['filename']}] (事件) 加入列表前再次確認為重複，跳過。")
        except Exception as e: logging.exception(f"[{os.path.basename(filepath)}] !! 處理 '{event_type_str}' 創建事件時發生未預期錯誤: {e}")
        finally: logging.info(f"---------- [Event End] 完成處理{event_type_str}: {filepath} ----------")

# --- 定期掃描函數 ---
def scan_and_process_new_files():
    global media_updates, processed_paths_set
    logging.info(">>> 開始定期輪詢新檔案/目錄...")
    batch_items_for_update = [] 
    for monitored_dir in MONITORED_DIRECTORIES:
        if not os.path.exists(monitored_dir): logging.warning(f"(輪詢) 監控目錄不存在: {monitored_dir}"); continue
        abs_monitored_dir = os.path.abspath(monitored_dir).lower()
        abs_collection_root = os.path.abspath("H:\\共用雲端硬碟\\@LiangTsaoEmby_本月更新\\全集").lower()
        if abs_monitored_dir == abs_collection_root:
            try:
                for item_name in os.listdir(monitored_dir):
                    item_path = os.path.join(monitored_dir, item_name)
                    if os.path.isdir(item_path):
                        abs_item_path_lower = os.path.abspath(item_path).lower()
                        if abs_item_path_lower not in processed_paths_set:
                            logging.info(f"(輪詢) 發現新目錄 (全集): {item_path}")
                            update_info = process_new_media(item_path, is_directory_event=True)
                            if update_info:
                                if abs_item_path_lower not in processed_paths_set:
                                    media_updates.append(update_info); processed_paths_set.add(abs_item_path_lower)
                                    batch_items_for_update.append(update_info)
                                    if len(batch_items_for_update) >= POLLING_BATCH_SAVE_COUNT:
                                        logging.info(f"(輪詢) 達到批次數量 {POLLING_BATCH_SAVE_COUNT} (目錄)，觸發儲存與 Git 更新...")
                                        media_updates.sort(key=lambda x: x.get('timestamp', datetime.datetime.min), reverse=True)
                                        trigger_update_process(); batch_items_for_update = []
                                else: logging.warning(f"(輪詢) 目錄 {item_name} 已被處理，跳過。")
            except Exception as e_list_dir: logging.exception(f"(輪詢) 遍歷目錄 {monitored_dir} 時出錯: {e_list_dir}")
            continue
        try:
            for root, _, files in os.walk(monitored_dir):
                for filename in files:
                    filepath = os.path.join(root, filename); abs_filepath_lower = os.path.abspath(filepath).lower()
                    if filename.lower().endswith(TARGET_EXTENSIONS):
                        if abs_filepath_lower not in processed_paths_set:
                            logging.info(f"(輪詢) 發現新檔案: {filepath}")
                            update_info = process_new_media(filepath, is_directory_event=False)
                            if update_info:
                                if abs_filepath_lower not in processed_paths_set:
                                    media_updates.append(update_info); processed_paths_set.add(abs_filepath_lower)
                                    batch_items_for_update.append(update_info)
                                    if len(batch_items_for_update) >= POLLING_BATCH_SAVE_COUNT:
                                        logging.info(f"(輪詢) 達到批次數量 {POLLING_BATCH_SAVE_COUNT} (檔案)，觸發儲存與 Git 更新...")
                                        media_updates.sort(key=lambda x: x.get('timestamp', datetime.datetime.min), reverse=True)
                                        trigger_update_process(); batch_items_for_update = []
                                else: logging.warning(f"(輪詢) 項目 {filename} 已被處理，跳過。")
        except Exception as e_walk: logging.exception(f"(輪詢) 遍歷目錄 {monitored_dir} 時 (os.walk) 出錯: {e_walk}")
    if batch_items_for_update:
        logging.info(f"(輪詢) 完成，處理剩餘 {len(batch_items_for_update)} 個新項目。觸發儲存與 Git 更新...")
        media_updates.sort(key=lambda x: x.get('timestamp', datetime.datetime.min), reverse=True)
        trigger_update_process()
    else: logging.info(">>> 定期輪詢完成，本輪無新檔案/目錄被實際加入列表。")

# --- 主程式 ---
if __name__ == "__main__":
    logging.info("="*30); logging.info("啟動檔案監視器腳本 (V9.1.2 - 補上 archive_html_shell)...") # 更新版本標示
    logging.info(f"將監控以下目錄: {MONITORED_DIRECTORIES}"); logging.info(f"Repo 路徑: {REPO_PATH}"); logging.info(f"主頁 HTML: {OUTPUT_HTML_FILE}"); logging.info(f"歷史頁 HTML: {ARCHIVE_HTML_FILE}"); logging.info(f"歷史頁 JS: {ARCHIVE_JS_FILE}"); logging.info(f"JSON 紀錄檔: {UPDATES_JSON_FILE}"); logging.info(f"主頁最大顯示項目: {MAX_ITEMS_ON_INDEX_PAGE}"); logging.info(f"輪詢間隔: {POLLING_INTERVAL_SECONDS} 秒"); logging.info(f"輪詢批次儲存數: {POLLING_BATCH_SAVE_COUNT}")
    try: result = subprocess.run(['git', '--version'], cwd=REPO_PATH, capture_output=True, text=True, check=True, encoding='utf-8'); logging.info(f"偵測到 Git 版本: {result.stdout.strip()}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e: logging.error(f"無法執行 Git 指令，請檢查 Git 安裝與 PATH。錯誤: {e}"); print("錯誤：無法執行 Git 指令。詳見日誌檔。"); exit()
    
    observer = Observer(); event_handler = MyHandler(); monitored_count = 0
    for path in MONITORED_DIRECTORIES:
        if os.path.exists(path): observer.schedule(event_handler, path, recursive=True); logging.info(f"已設定監控: {path}"); monitored_count += 1
        else: logging.warning(f"目錄不存在，無法監控: {path}")
    if monitored_count == 0: logging.error("沒有任何有效的目錄被監控，腳本即將退出。"); print("錯誤：沒有任何有效的目錄被監控。"); exit()
    
    observer.start(); logging.info("文件監視器已啟動，等待檔案變更與定期輪詢..."); print("文件監視器已啟動，等待檔案變更與定期輪詢...")
    
    last_poll_time = time.time()
    try:
        main_loop_counter = 0
        while True:
            time.sleep(10)
            main_loop_counter += 1
            if main_loop_counter % 360 == 0: 
                logging.info(f"主循環正常運行中。media_updates 長度: {len(media_updates)}, processed_paths_set 長度: {len(processed_paths_set)}")
            current_time = time.time()
            if (current_time - last_poll_time) >= POLLING_INTERVAL_SECONDS:
                logging.info(f"--- 觸發定期輪詢任務 (距離上次 {int(current_time - last_poll_time)} 秒) ---")
                scan_and_process_new_files()
                last_poll_time = time.time()
    except KeyboardInterrupt:
        observer.stop()
        logging.info("收到停止訊號 (KeyboardInterrupt)。")
        if git_timer is not None and git_timer.is_alive():
            git_timer.cancel()
            logging.info("取消了待處理的延遲 Git 操作。")
    except Exception as e:
        logging.exception(f"監視器主循環發生未預期錯誤: {e}")
    finally:
        if observer.is_alive(): 
            observer.join()
        logging.info("文件監視器已停止。")
        print("文件監視器已停止。") 