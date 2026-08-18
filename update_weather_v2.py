#!/usr/bin/env python3
"""
天气看板共享数据更新脚本 v2（安全加固版）

功能：
- 主数据源：Open-Meteo（免费无限制）→ 当前天气 + 3天预报
- 预警数据源：和风天气（仅预警，月度配额50,000次）
- 配额保护：月用量>45,000时切换为Open-Meteo衍生预警
- 输出格式与原脚本完全兼容，所有看板无需修改

安全说明：
- API Key 和 GitHub Token 通过环境变量或配置文件读取，禁止硬编码
- 详见部署指南.md

每日执行4次：08:00 / 12:00 / 18:00 / 22:00
API调用预估：每次约115次（仅预警），月用量≈13,800次
"""

import json, requests, time, sys, base64, os, re as _re
from datetime import datetime

# ============================================================
# 配置区 - 从环境变量或配置文件读取，禁止硬编码敏感信息
# ============================================================

def load_config():
    """加载配置，优先级：环境变量 > config.json > 默认值"""
    config = {}
    
    # 尝试从 config.json 读取
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, 'config.json')
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as cf:
                config = json.load(cf)
        except Exception as e:
            print(f"[警告] 读取配置文件失败: {e}")
    
    return {
        'WARNING_KEY': os.environ.get('QWEATHER_API_KEY', config.get('WARNING_KEY', '')),
        'WARNING_DOMAIN': os.environ.get('QWEATHER_API_DOMAIN', config.get('WARNING_DOMAIN', 'devapi.qweather.com')),
        'GITHUB_TOKEN': os.environ.get('GITHUB_TOKEN', config.get('GITHUB_TOKEN', '')),
        'GITHUB_OWNER': os.environ.get('GITHUB_OWNER', config.get('GITHUB_OWNER', '')),
        'GITHUB_REPO': os.environ.get('GITHUB_REPO', config.get('GITHUB_REPO', '')),
    }

CFG = load_config()

# 和风天气（仅预警）
WARNING_KEY = CFG['WARNING_KEY']
WARNING_DOMAIN = CFG['WARNING_DOMAIN']

if not WARNING_KEY:
    print("[警告] 和风天气 API Key 未配置！预警数据将无法获取。")
    print("       请设置环境变量 QWEATHER_API_KEY 或创建 config.json 文件。")

# GitHub 配置（用于推送数据，可选）
TOKEN = CFG['GITHUB_TOKEN']
OWNER = CFG['GITHUB_OWNER']
REPO = CFG['GITHUB_REPO']
DATA_PATH = 'data/weather.json'

if not TOKEN:
    print("[提示] GitHub Token 未配置，数据更新后将仅保存在本地，不会推送到远程。")

# 关注的预警类型和级别
FOCUS_WARNING_TYPES = ['雷电', '暴雨', '台风', '强对流', '冰雹']
FOCUS_WARNING_LEVELS = ['黄色', '橙色', '红色']

# Open-Meteo
OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
BATCH_SIZE = 80  # 每批最多80城

# 配额管理
MONTHLY_QUOTA = 50000
QUOTA_THRESHOLD = 45000  # 超过此值切换为衍生预警
USAGE_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api_usage.log')

WMO_TO_CN = {
    0: ('晴', '100'), 1: ('晴', '100'), 2: ('多云', '101'), 3: ('阴', '104'),
    45: ('雾', '106'), 48: ('雾', '106'),
    51: ('小雨', '107'), 53: ('中雨', '108'), 55: ('大雨', '109'),
    56: ('冻雨', '110'), 57: ('冻雨', '110'),
    61: ('小雨', '107'), 63: ('中雨', '108'), 65: ('大雨', '109'),
    66: ('冻雨', '110'), 67: ('冻雨', '110'),
    71: ('小雪', '111'), 73: ('中雪', '112'), 75: ('大雪', '113'),
    77: ('雨夹雪', '114'),
    80: ('小阵雨', '115'), 81: ('中阵雨', '116'), 82: ('大暴雨', '117'),
    85: ('小阵雪', '118'), 86: ('大阵雪', '119'),
    95: ('雷阵雨', '120'), 96: ('雷阵雨伴冰雹', '121'), 99: ('雷阵雨伴大冰雹', '122')
}

# 和风天气颜色映射
COLOR_MAP = {'red': '红色', 'orange': '橙色', 'yellow': '黄色', 'blue': '蓝色'}

# ============================================================
# 城市列表（115城）
# ============================================================
CITIES = {
    "江门": {"lon":113.08,"lat":22.58,"qid":"101281401"},
    "成都": {"lon":104.07,"lat":30.67,"qid":"101270101"},
    "龙岩": {"lon":117.02,"lat":25.08,"qid":"101230701"},
    "漳州": {"lon":117.65,"lat":24.51,"qid":"101230601"},
    "北京": {"lon":116.41,"lat":39.9,"qid":"101010100"},
    "株洲": {"lon":113.16,"lat":27.83,"qid":"101250301"},
    "东莞": {"lon":113.74,"lat":23.05,"qid":"101281601"},
    "重庆": {"lon":106.54,"lat":29.59,"qid":"101040100"},
    "杭州": {"lon":120.19,"lat":30.26,"qid":"101210101"},
    "泉州": {"lon":118.59,"lat":24.94,"qid":"101230501"},
    "嘉兴": {"lon":120.76,"lat":30.77,"qid":"101210301"},
    "六安": {"lon":116.5,"lat":31.76,"qid":"101220701"},
    "合肥": {"lon":117.27,"lat":31.86,"qid":"101220101"},
    "上海": {"lon":121.46,"lat":31.28,"qid":"101020100"},
    "佛山": {"lon":113.12,"lat":23.02,"qid":"101280801"},
    "苏州": {"lon":120.62,"lat":31.32,"qid":"101190101"},
    "益阳": {"lon":112.32,"lat":28.59,"qid":"101250501"},
    "武汉": {"lon":114.31,"lat":30.52,"qid":"101200101"},
    "南昌": {"lon":115.89,"lat":28.68,"qid":"101240101"},
    "南京": {"lon":118.78,"lat":32.04,"qid":"101190101"},
    "长沙": {"lon":112.94,"lat":28.23,"qid":"101250101"},
    "淮安": {"lon":119.02,"lat":33.59,"qid":"101190901"},
    "蚌埠": {"lon":117.35,"lat":32.93,"qid":"101220201"},
    "徐州": {"lon":117.18,"lat":34.27,"qid":"101190801"},
    "盐城": {"lon":120.13,"lat":33.38,"qid":"101190701"},
    "贵阳": {"lon":106.71,"lat":26.57,"qid":"101260101"},
    "黄石": {"lon":115.07,"lat":30.2,"qid":"101200601"},
    "广州": {"lon":113.26,"lat":23.13,"qid":"101280101"},
    "宿迁": {"lon":118.28,"lat":33.96,"qid":"101191301"},
    "宁波": {"lon":121.55,"lat":29.87,"qid":"101210401"},
    "宁德": {"lon":119.52,"lat":26.65,"qid":"101230301"},
    "福州": {"lon":119.3,"lat":26.08,"qid":"101230101"},
    "南平": {"lon":118.18,"lat":26.64,"qid":"101230901"},
    "莆田": {"lon":119.01,"lat":25.45,"qid":"101230401"},
    "珠海": {"lon":113.58,"lat":22.27,"qid":"101280701"},
    "丽水": {"lon":119.92,"lat":28.45,"qid":"119.92,28.45"},
    "济南": {"lon":117.0,"lat":36.67,"qid":"101120101"},
    "台州": {"lon":121.42,"lat":28.66,"qid":"101210901"},
    "无锡": {"lon":120.3,"lat":31.57,"qid":"101190201"},
    "温州": {"lon":120.65,"lat":28.0,"qid":"101210701"},
    "绍兴": {"lon":120.58,"lat":30.0,"qid":"101210501"},
    "南宁": {"lon":108.37,"lat":22.82,"qid":"101300101"},
    "柳州": {"lon":109.41,"lat":24.33,"qid":"101300301"},
    "九江": {"lon":116.0,"lat":29.71,"qid":"101240201"},
    "南通": {"lon":120.86,"lat":31.98,"qid":"101190501"},
    "大连": {"lon":121.61,"lat":38.91,"qid":"101070201"},
    "哈尔滨": {"lon":126.63,"lat":45.75,"qid":"101050101"},
    "长春": {"lon":125.32,"lat":43.88,"qid":"101060101"},
    "沈阳": {"lon":123.43,"lat":41.8,"qid":"101070101"},
    "保定": {"lon":115.46,"lat":38.87,"qid":"101090201"},
    "承德": {"lon":117.96,"lat":40.95,"qid":"117.96,40.95"},
    "廊坊": {"lon":116.7,"lat":39.52,"qid":"101060201"},
    "石家庄": {"lon":114.51,"lat":38.04,"qid":"101090101"},
    "唐山": {"lon":118.18,"lat":39.63,"qid":"101090101"},
    "包头": {"lon":109.84,"lat":40.66,"qid":"109.84,40.66"},
    "天津": {"lon":117.2,"lat":39.13,"qid":"101030100"},
    "滁州": {"lon":118.31,"lat":32.3,"qid":"101221101"},
    "芜湖": {"lon":118.38,"lat":31.33,"qid":"101220301"},
    "常熟": {"lon":120.74,"lat":31.64,"qid":"120.74,31.64"},
    "常州": {"lon":119.97,"lat":31.79,"qid":"101191101"},
    "连云港": {"lon":119.16,"lat":34.59,"qid":"101191001"},
    "扬州": {"lon":119.42,"lat":32.39,"qid":"101190601"},
    "镇江": {"lon":119.44,"lat":32.2,"qid":"101190301"},
    "青岛": {"lon":120.33,"lat":36.07,"qid":"101120201"},
    "泰州": {"lon":119.9,"lat":32.49,"qid":"101190401"},
    "威海": {"lon":122.12,"lat":37.52,"qid":"101121301"},
    "潍坊": {"lon":119.1,"lat":36.62,"qid":"101120601"},
    "烟台": {"lon":121.39,"lat":37.52,"qid":"101120501"},
    "太原": {"lon":112.55,"lat":37.87,"qid":"101100101"},
    "湖州": {"lon":120.09,"lat":30.86,"qid":"101210201"},
    "金华": {"lon":119.64,"lat":29.12,"qid":"101210801"},
    "昆山": {"lon":120.95,"lat":31.39,"qid":"120.95,31.39"},
    "义乌": {"lon":120.06,"lat":29.32,"qid":"120.06,29.32"},
    "惠州": {"lon":114.42,"lat":23.09,"qid":"101280301"},
    "清远": {"lon":113.01,"lat":23.7,"qid":"101281301"},
    "汕头": {"lon":116.69,"lat":23.39,"qid":"101281501"},
    "中山": {"lon":113.38,"lat":22.52,"qid":"101281701"},
    "洛阳": {"lon":112.44,"lat":34.63,"qid":"101180901"},
    "新乡": {"lon":113.85,"lat":35.3,"qid":"101180401"},
    "郑州": {"lon":113.65,"lat":34.76,"qid":"101180101"},
    "宜昌": {"lon":111.29,"lat":30.69,"qid":"101200901"},
    "湘潭": {"lon":112.91,"lat":27.87,"qid":"101250201"},
    "岳阳": {"lon":113.09,"lat":29.37,"qid":"101250601"},
    "西安": {"lon":108.95,"lat":34.27,"qid":"101110101"},
    "广汉": {"lon":104.28,"lat":31.0,"qid":"104.28,31.0"},
    "眉山": {"lon":103.83,"lat":30.05,"qid":"103.83,30.05"},
    "昆明": {"lon":102.73,"lat":25.04,"qid":"101290101"},
    "佳木斯": {"lon":130.36,"lat":46.82,"qid":"101050401"},
    "七台河": {"lon":130.83,"lat":45.77,"qid":"130.83,45.77"},
    "朝阳": {"lon":120.44,"lat":41.57,"qid":"120.44,41.57"},
    "抚顺": {"lon":123.96,"lat":41.88,"qid":"123.96,41.88"},
    "铁岭": {"lon":123.85,"lat":42.28,"qid":"123.85,42.28"},
    "福清": {"lon":119.38,"lat":25.72,"qid":"119.38,25.72"},
    "营口": {"lon":122.23,"lat":40.67,"qid":"122.23,40.67"},
    "衡水": {"lon":115.67,"lat":37.73,"qid":"115.67,37.73"},
    "秦皇岛": {"lon":119.57,"lat":39.94,"qid":"101091101"},
    "张家口": {"lon":114.87,"lat":40.82,"qid":"101090301"},
    "晋城": {"lon":112.85,"lat":35.49,"qid":"112.85,35.49"},
    "三明": {"lon":117.63,"lat":26.26,"qid":"101230801"},
    "临夏": {"lon":103.21,"lat":35.6,"qid":"103.21,35.6"},
    "深圳": {"lon":114.07,"lat":22.62,"qid":"101280601"},
    "抚州": {"lon":116.35,"lat":27.95,"qid":"101241101"},
    "德州": {"lon":116.29,"lat":37.45,"qid":"116.29,37.45"},
    "日照": {"lon":119.46,"lat":35.42,"qid":"119.46,35.42"},
    "舟山": {"lon":122.1,"lat":30.0,"qid":"101210601"},
    "海口": {"lon":110.35,"lat":20.02,"qid":"101310101"},
    "张家港": {"lon":120.55,"lat":31.88,"qid":"120.55,31.88"},
    "嘉峪关": {"lon":98.28,"lat":39.77,"qid":"98.28,39.77"},
    "怒江": {"lon":98.85,"lat":25.86,"qid":"98.85,25.86"},
    "赣州": {"lon":114.93,"lat":25.83,"qid":"101240701"},
    "玉林": {"lon":110.15,"lat":22.65,"qid":"101300501"},
    "黔南": {"lon":107.52,"lat":26.25,"qid":"107.52,26.25"},
    "厦门": {"lon":118.1,"lat":24.46,"qid":"101230201"},
    "雅安": {"lon":103.01,"lat":29.98,"qid":"103.01,29.98"},
    "文山": {"lon":104.24,"lat":23.37,"qid":"104.24,23.37"}
}

# ============================================================
# 工具函数
# ============================================================

def wind_speed_to_scale(speed_kmh):
    """km/h → 蒲福风力等级"""
    thresholds = [1, 5, 11, 19, 28, 38, 49, 61, 74, 88, 102, 117, 133, 149, 166, 183, 201, 220]
    for i, t in enumerate(thresholds):
        if speed_kmh <= t:
            return str(i)
    return '17'


def wind_deg_to_dir(deg):
    """风向角度 → 中文风向"""
    dirs = ['北', '东北', '东', '东南', '南', '西南', '西', '西北']
    return dirs[round(deg / 45) % 8] + '风'


def wmo_to_qweather(code):
    """WMO天气代码 → (中文描述, 和风icon编码)"""
    return WMO_TO_CN.get(code, ('未知', '100'))


# ============================================================
# 配额管理
# ============================================================

def log_api_usage(count, operation):
    """记录API调用日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"{timestamp} | {operation} | {count}次调用\n"
    with open(USAGE_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line)


def get_monthly_usage():
    """获取本月已使用的和风天气API次数"""
    if not os.path.exists(USAGE_LOG_FILE):
        return 0
    current_month = datetime.now().strftime('%Y-%m')
    total = 0
    with open(USAGE_LOG_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith(current_month):
                try:
                    parts = line.strip().split('|')
                    count = int(parts[2].strip().replace('次调用', ''))
                    total += count
                except (ValueError, IndexError):
                    pass
    return total


def should_use_qweather_warnings():
    """检查是否应该使用和风天气预警（配额充足时返回True）"""
    used = get_monthly_usage()
    print(f"[配额] 本月和风天气已用: {used}/{MONTHLY_QUOTA} ({used/MONTHLY_QUOTA*100:.1f}%)")
    if used > QUOTA_THRESHOLD:
        print(f"[配额] 超过阈值{QUOTA_THRESHOLD}，切换为Open-Meteo衍生预警")
        return False
    return True


# ============================================================
# Open-Meteo 批量获取天气 + 预报
# ============================================================

def fetch_open_meteo_batch(city_list):
    """
    批量获取Open-Meteo数据
    city_list: [(name, info), ...] 城市列表
    返回: dict[qid] = {current_data, daily_data}
    """
    lats = ','.join(str(c[1]['lat']) for c in city_list)
    lons = ','.join(str(c[1]['lon']) for c in city_list)

    params = {
        'latitude': lats,
        'longitude': lons,
        'current': ','.join([
            'temperature_2m',
            'relative_humidity_2m',
            'apparent_temperature',
            'weather_code',
            'wind_speed_10m',
            'wind_direction_10m',
            'wind_gusts_10m'
        ]),
        'daily': ','.join([
            'weather_code',
            'temperature_2m_max',
            'temperature_2m_min',
            'precipitation_sum',
            'wind_speed_10m_max',
            'wind_gusts_10m_max'
        ]),
        'timezone': 'Asia/Shanghai',
        'forecast_days': 3
    }

    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [ERROR] Open-Meteo批量请求失败: {e}")
        return None


def parse_open_meteo_response(batch_data, city_list):
    """
    解析Open-Meteo批量响应
    返回: weather_dict, forecast_dict
    """
    weather = {}
    forecast = {}
    now_str = datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')

    if not batch_data:
        return weather, forecast

    # Open-Meteo 批量返回可能是单个dict（1城时）或list
    results = batch_data if isinstance(batch_data, list) else [batch_data]

    for i, (name, info) in enumerate(city_list):
        if i >= len(results):
            break

        result = results[i]
        qid = info['qid']

        # 跳过错误结果
        if 'error' in result:
            print(f"  [WARN] {name}: {result.get('reason', 'unknown error')}")
            continue

        # --- 当前天气 ---
        cur = result.get('current', {})
        wmo_code = cur.get('weather_code', 0)
        text_cn, icon_code = wmo_to_qweather(wmo_code)
        temp = cur.get('temperature_2m', 0)
        feels = cur.get('apparent_temperature', temp)
        humidity = cur.get('relative_humidity_2m', 0)
        wind_spd = cur.get('wind_speed_10m', 0)
        wind_dir_deg = cur.get('wind_direction_10m', 0)

        weather[qid] = {
            'temp': str(int(round(temp))),
            'icon': icon_code,
            'text': text_cn,
            'windDir': wind_deg_to_dir(wind_dir_deg),
            'windScale': wind_speed_to_scale(wind_spd),
            'windSpeed': str(int(round(wind_spd))),
            'humidity': str(int(round(humidity))),
            'feelsLike': str(int(round(feels))),
            'updateTime': now_str
        }

        # --- 3天预报 ---
        daily = result.get('daily', {})
        dates = daily.get('time', [])
        t_max = daily.get('temperature_2m_max', [])
        t_min = daily.get('temperature_2m_min', [])
        codes = daily.get('weather_code', [])
        precip = daily.get('precipitation_sum', [])
        max_wind = daily.get('wind_speed_10m_max', [])

        fc_list = []
        for j in range(min(len(dates), 3)):
            day_code = codes[j] if j < len(codes) else 0
            day_text, day_icon = wmo_to_qweather(day_code)
            fc_list.append({
                'fxDate': dates[j],
                'tempMax': str(int(round(t_max[j]))) if j < len(t_max) else '',
                'tempMin': str(int(round(t_min[j]))) if j < len(t_min) else '',
                'iconDay': day_icon,
                'textDay': day_text,
                '_precip': precip[j] if j < len(precip) else 0,
                '_maxWind': max_wind[j] if j < len(max_wind) else 0,
                '_weatherCode': day_code
            })
        forecast[qid] = fc_list

    return weather, forecast


def fetch_all_weather_open_meteo():
    """
    用Open-Meteo批量获取所有城市的天气+预报
    返回: weather_dict, forecast_dict
    """
    city_items = list(CITIES.items())
    all_weather = {}
    all_forecast = {}

    # 分批处理
    num_batches = (len(city_items) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_idx in range(num_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(city_items))
        batch = city_items[start:end]
        batch_names = [c[0] for c in batch]
        print(f"  批次 {batch_idx+1}/{num_batches}: {len(batch)}城 ({batch_names[0]}...{batch_names[-1]})")

        batch_data = fetch_open_meteo_batch(batch)
        w, f = parse_open_meteo_response(batch_data, batch)
        all_weather.update(w)
        all_forecast.update(f)

        # 批次间短暂间隔
        if batch_idx < num_batches - 1:
            time.sleep(1)

    return all_weather, all_forecast


# ============================================================
# 和风天气预警
# ============================================================

def map_qweather_alert(alert):
    """将和风天气预警数据映射为兼容格式"""
    color_code = alert.get('color', {}).get('code', '')
    severity = COLOR_MAP.get(color_code, alert.get('severity', '蓝色'))
    type_name = alert.get('eventType', {}).get('name', '')
    is_active = alert.get('messageType', {}).get('code') != 'cancel'
    return {
        'id': alert.get('id', ''),
        'sender': alert.get('senderName', ''),
        'pubTime': alert.get('issuedTime', ''),
        'title': alert.get('headline', ''),
        'startTime': alert.get('effectiveTime', ''),
        'endTime': alert.get('expireTime', ''),
        'status': 'active' if is_active else 'cancel',
        'level': severity,
        'severity': severity,
        'type': alert.get('eventType', {}).get('code', ''),
        'typeName': type_name,
        'text': alert.get('description', ''),
        'headline': alert.get('headline', ''),
        'description': alert.get('description', ''),
        'source': 'qweather'
    }


def fetch_qweather_warnings():
    """
    从和风天气获取所有城市预警
    返回: warnings_dict, api_call_count
    """
    warnings = {}
    call_count = 0

    for name, info in CITIES.items():
        qid = info['qid']
        lat, lon = info['lat'], info['lon']
        try:
            url = f'https://{WARNING_DOMAIN}/weatheralert/v1/current/{lat}/{lon}?key={WARNING_KEY}'
            resp = requests.get(url, timeout=10)
            call_count += 1
            data = resp.json()

            if data.get('metadata'):
                if data['metadata'].get('zeroResult') or not data.get('alerts'):
                    pass
                else:
                    alerts = [map_qweather_alert(a) for a in data['alerts']]
                    filtered = [a for a in alerts
                                if a['typeName'] in FOCUS_WARNING_TYPES
                                and a['level'] in FOCUS_WARNING_LEVELS]
                    if filtered:
                        warnings[qid] = {'warning': filtered}
        except Exception as e:
            print(f"  [WARN] {name}预警获取失败: {e}")

        time.sleep(0.05)

    return warnings, call_count


# ============================================================
# Open-Meteo 衍生预警（fallback）
# ============================================================

def derive_warnings_from_open_meteo(forecast_dict):
    """
    基于Open-Meteo预报数据衍生预警
    规则：
    - 天气代码95-99 → 雷电预警（橙色）
    - 日降水量>50mm → 暴雨预警（橙色）
    - 天气代码96/99 → 冰雹预警（橙色）
    """
    warnings = {}
    now_str = datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')

    for qid, fc_list in forecast_dict.items():
        city_warnings = []

        for day_fc in fc_list:
            code = day_fc.get('_weatherCode', 0)
            precip = day_fc.get('_precip', 0)
            date = day_fc.get('fxDate', '')

            # 雷电预警 (95-99)
            if code in (95, 96, 97, 98, 99):
                city_warnings.append({
                    'id': f'om-thunder-{qid}-{date}',
                    'title': f'雷电预警（橙色）',
                    'level': '橙色',
                    'typeName': '雷电',
                    'text': f'{date}预计有雷电活动，请注意防范。',
                    'pubTime': now_str,
                    'startTime': f'{date}T00:00:00+08:00',
                    'endTime': f'{date}T23:59:00+08:00',
                    'status': 'active',
                    'severity': '橙色',
                    'type': 'thunder',
                    'headline': f'雷电预警（橙色）',
                    'description': f'{date}预计有雷电活动，请注意防范。',
                    'sender': 'Open-Meteo',
                    'source': 'open-meteo'
                })

            # 暴雨预警（日降水量>50mm）
            if precip and precip > 50:
                city_warnings.append({
                    'id': f'om-rain-{qid}-{date}',
                    'title': f'暴雨预警（橙色）',
                    'level': '橙色',
                    'typeName': '暴雨',
                    'text': f'{date}预计降水量{precip:.1f}mm，请注意防范。',
                    'pubTime': now_str,
                    'startTime': f'{date}T00:00:00+08:00',
                    'endTime': f'{date}T23:59:00+08:00',
                    'status': 'active',
                    'severity': '橙色',
                    'type': 'rainstorm',
                    'headline': f'暴雨预警（橙色）',
                    'description': f'{date}预计降水量{precip:.1f}mm，请注意防范。',
                    'sender': 'Open-Meteo',
                    'source': 'open-meteo'
                })

            # 冰雹预警 (96/99)
            if code in (96, 99):
                city_warnings.append({
                    'id': f'om-hail-{qid}-{date}',
                    'title': f'冰雹预警（橙色）',
                    'level': '橙色',
                    'typeName': '冰雹',
                    'text': f'{date}可能出现冰雹天气，请注意防范。',
                    'pubTime': now_str,
                    'startTime': f'{date}T00:00:00+08:00',
                    'endTime': f'{date}T23:59:00+08:00',
                    'status': 'active',
                    'severity': '橙色',
                    'type': 'hail',
                    'headline': f'冰雹预警（橙色）',
                    'description': f'{date}可能出现冰雹天气，请注意防范。',
                    'sender': 'Open-Meteo',
                    'source': 'open-meteo'
                })

        # 去重：同一城市同一类型只保留一个
        seen = set()
        unique_warnings = []
        for w in city_warnings:
            key = w['typeName']
            if key not in seen:
                seen.add(key)
                unique_warnings.append(w)

        if unique_warnings:
            warnings[qid] = {'warning': unique_warnings}

    return warnings


# ============================================================
# 台风信息获取（中央气象台台风网 API）
# ============================================================

# 强度等级映射
NMC_GRADE_CN = {
    'TD': '热带低压', 'TS': '热带风暴', 'STS': '强热带风暴',
    'TY': '台风', 'STY': '强台风', 'SuperTY': '超强台风'
}

# 移动方向英文→中文
DIR_CN = {
    'N': '北', 'NNE': '北东北', 'NE': '东北', 'ENE': '东东北',
    'E': '东', 'ESE': '东东南', 'SE': '东南', 'SSE': '南东南',
    'S': '南', 'SSW': '南西南', 'SW': '西南', 'WSW': '西西南',
    'W': '西', 'WNW': '西西北', 'NW': '西北', 'NNW': '北西北'
}

def fetch_nmc_typhoon():
    """
    从中央气象台台风网获取活跃台风实时数据。
    API: http://typhoon.nmc.cn/weatherservice/typhoon/jsons/
    返回结构化台风数据，含实时位置、强度、风圈、中央气象台预报路径。
    无活跃台风时返回 {"active": False}
    """
    import re as _re

    headers = {'User-Agent': 'Mozilla/5.0 (compatible; WeatherDashboard/2.0)'}
    nmc_base = 'http://typhoon.nmc.cn/weatherservice'

    # 1. 获取活跃台风列表（JSONP格式）
    try:
        resp = requests.get(f'{nmc_base}/typhoon/jsons/list_default',
                           headers=headers, verify=False, timeout=10)
        if resp.status_code != 200:
            print(f"  [台风] NMC列表请求失败: HTTP {resp.status_code}")
            return {"active": False}
        # 解析JSONP: typhoon_jsons_list_default({...})
        json_match = _re.search(r'\((\{.*\})\)', resp.text, _re.S)
        if not json_match:
            print("  [台风] NMC列表解析失败: 无JSON数据")
            return {"active": False}
        list_data = json.loads(json_match.group(1))
    except Exception as e:
        print(f"  [台风] NMC列表请求异常: {e}")
        return {"active": False}

    # 2. 筛选活跃台风（status == "start"）
    active_list = [t for t in list_data.get('typhoonList', []) if len(t) >= 8 and t[7] == 'start']
    if not active_list:
        print("  [台风] 当前无活跃台风")
        return {"active": False}

    # 3. 获取第一个活跃台风的详细数据
    typhoon_id = active_list[0][0]  # 内部ID
    typhoon_num = active_list[0][3]  # 编号如2612
    typhoon_name_cn = active_list[0][2]  # 中文名

    try:
        resp2 = requests.get(f'{nmc_base}/typhoon/jsons/view_{typhoon_id}',
                            headers=headers, verify=False, timeout=10)
        if resp2.status_code != 200:
            print(f"  [台风] NMC详情请求失败: HTTP {resp2.status_code}")
            return {"active": False}
        json_match2 = _re.search(r'\((\{.*\})\)', resp2.text, _re.S)
        if not json_match2:
            print("  [台风] NMC详情解析失败")
            return {"active": False}
        detail = json.loads(json_match2.group(1))
    except Exception as e:
        print(f"  [台风] NMC详情请求异常: {e}")
        return {"active": False}

    tf = detail.get('typhoon', [])
    if len(tf) < 9 or not tf[8]:
        print("  [台风] 数据结构异常")
        return {"active": False}

    # 4. 解析最新路径点
    track_points = tf[8]
    latest = track_points[-1]  # 最后一个点是最新的
    # latest格式: [id, datetime_str, timestamp_ms, grade, lon, lat, pressure, wind_speed, move_dir, radius7, [], forecast_dict, [analysis_time...]]
    grade_code = latest[3] if len(latest) > 3 else ''
    lon = latest[4] if len(latest) > 4 else 0
    lat = latest[5] if len(latest) > 5 else 0
    pressure = latest[6] if len(latest) > 6 else 0
    wind_speed = latest[7] if len(latest) > 7 else 0  # m/s
    move_dir_en = latest[8] if len(latest) > 8 else ''
    radius7 = latest[9] if len(latest) > 9 else 0  # 七级风圈半径km
    forecast_dict = latest[11] if len(latest) > 11 else {}
    analysis_time_arr = latest[12] if len(latest) > 12 else []

    # 风力等级换算（m/s → 级）
    wind_level = ''
    if wind_speed > 0:
        if wind_speed >= 51.0: wind_level = '17级'
        elif wind_speed >= 46.2: wind_level = '16级'
        elif wind_speed >= 41.5: wind_level = '15级'
        elif wind_speed >= 37.0: wind_level = '14级'
        elif wind_speed >= 32.7: wind_level = '13级'
        elif wind_speed >= 28.5: wind_level = '12级'
        elif wind_speed >= 24.5: wind_level = '11级'
        elif wind_speed >= 20.8: wind_level = '10级'
        elif wind_speed >= 17.2: wind_level = '9级'
        elif wind_speed >= 13.9: wind_level = '8级'
        elif wind_speed >= 10.8: wind_level = '7级'
        elif wind_speed >= 8.0: wind_level = '6级'
        else: wind_level = f'{wind_speed}m/s'

    strength_cn = NMC_GRADE_CN.get(grade_code, grade_code)
    move_dir_cn = DIR_CN.get(move_dir_en, move_dir_en)

    # 5. 解析中央气象台(BABJ)预报路径
    forecast_track = []
    if forecast_dict and 'BABJ' in forecast_dict:
        for fp in forecast_dict['BABJ']:
            # fp格式: [pred_hour, datetime, pred_lon, pred_lat, pred_pressure, pred_wind, 'BABJ', pred_grade]
            pred_hour = fp[0] if len(fp) > 0 else 0
            pred_lon = fp[2] if len(fp) > 2 else 0
            pred_lat = fp[3] if len(fp) > 3 else 0
            pred_pressure = fp[4] if len(fp) > 4 else 0
            pred_wind = fp[5] if len(fp) > 5 else 0
            pred_grade = fp[7] if len(fp) > 7 else ''
            forecast_track.append({
                'hour': pred_hour,
                'lon': pred_lon,
                'lat': pred_lat,
                'pressure': pred_pressure,
                'wind': pred_wind,
                'grade': NMC_GRADE_CN.get(pred_grade, pred_grade)
            })

    # 6. 推算登陆预报（从预报路径中找首次进入陆地/接近海岸的点）
    landing_forecast = ''
    if forecast_track:
        # 简单逻辑：找预报中纬度最高且风速开始快速减弱的点（通常对应登陆后）
        for fp in forecast_track:
            if fp['wind'] < wind_speed * 0.5 and fp['hour'] > 12:
                landing_forecast = f"预计{fp['hour']}小时后减弱为{fp['grade']}"
                break

    # 7. 构建输出
    analysis_time = analysis_time_arr[0] if analysis_time_arr else ''
    # 格式化分析时间
    if analysis_time and len(analysis_time) >= 12:
        analysis_display = f"{analysis_time[:4]}-{analysis_time[4:6]}-{analysis_time[6:8]} {analysis_time[8:10]}:{analysis_time[10:12]}"
    else:
        analysis_display = analysis_time

    typhoon_info = {
        "active": True,
        "name": typhoon_name_cn,
        "nameEn": active_list[0][1],
        "stormId": str(typhoon_num),
        "strength": strength_cn,
        "grade": grade_code,
        "windLevel": wind_level,
        "windSpeed": wind_speed,
        "pressure": pressure,
        "lat": lat,
        "lon": lon,
        "moveDir": move_dir_cn,
        "moveDirEn": move_dir_en,
        "radius7": radius7,
        "analysisTime": analysis_display,
        "forecast": forecast_track,
        "landingForecast": landing_forecast,
        "source": "中央气象台",
        "updateTime": datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')
    }

    print(f"  ✓ 台风数据: {typhoon_name_cn}({active_list[0][1]}) {strength_cn}({wind_level}) "
          f"风速{wind_speed}m/s 气压{pressure}hPa 位置{lat}°N,{lon}°E")
    if forecast_track:
        print(f"  ✓ 中央气象台预报: {len(forecast_track)}个时次 ({forecast_track[0]['hour']}h~{forecast_track[-1]['hour']}h)")
    return typhoon_info


# 保留旧函数名作为兼容别名
def extract_typhoon_info(warnings_dict):
    """兼容旧调用，实际使用中央气象台API获取台风数据"""
    return fetch_nmc_typhoon()


# ============================================================
# 以下为旧版预警文本解析（已弃用，保留备用）
# ============================================================
def _extract_typhoon_info_legacy(warnings_dict):
    """
    [已弃用] 从和风天气预警数据中提取台风信息。
    现在改用 fetch_nmc_typhoon() 从中央气象台获取。
    """
    import re

    typhoon_alerts = []
    for qid, data in warnings_dict.items():
        warning_list = data.get('warning', [])
        for alert in warning_list:
            if alert.get('typeName') == '台风':
                typhoon_alerts.append(alert)

    if not typhoon_alerts:
        return {"active": False}

    # 按发布时间排序，取最新的一条
    typhoon_alerts.sort(key=lambda a: a.get('pubTime', ''), reverse=True)
    latest = typhoon_alerts[0]

    # 从标题和文本中提取台风信息
    title = latest.get('title', '') or latest.get('headline', '')
    text = latest.get('text', '') or latest.get('description', '')
    combined = f"{title} {text}"

    # 提取台风名称：标题中常见格式 "台风黄色预警"、"XX市台风蓝色预警" 等
    # 也可能包含台风名称如"台风"红霞""
    name_match = re.search(r'[""\u201c\u300c]([\u4e00-\u9fff]+)[""\u201d\u300d]', combined)
    typhoon_name = name_match.group(1) if name_match else ''

    # 如果没有从引号中提取到名称，尝试从常见描述模式提取
    if not typhoon_name:
        name_match2 = re.search(r'今年第(\d+)号台风[""\u201c\u300c]?([\u4e00-\u9fff]+)?[""\u201d\u300d]?', combined)
        if name_match2:
            typhoon_name = name_match2.group(2) or ''

    # 提取台风编号
    storm_id_match = re.search(r'第(\d+)号', combined)
    storm_id = storm_id_match.group(0) if storm_id_match else ''

    # 提取强度等级：如"台风级"、"强台风级"、"超强台风级"、"热带风暴级"
    strength_match = re.search(r'(超强台风级|强台风级|台风级|强热带风暴级|热带风暴级|热带低压级)', combined)
    strength = strength_match.group(1) if strength_match else ''

    # 提取风力等级：如"12级"、"13-14级"
    level_match = re.search(r'(\d+(?:-\d+)?)级', combined)
    level_str = level_match.group(1) if level_match else ''

    # 提取风速：如"33m/s"、"38米/秒"
    speed_match = re.search(r'(\d+(?:\.\d+)?)[米m][/每]秒', combined)
    speed = speed_match.group(0) if speed_match else ''

    # 提取气压：如"975hPa"、"975百帕"
    pressure_match = re.search(r'(\d{3,4})\s*(?:hPa|百帕|毫巴)', combined)
    pressure = int(pressure_match.group(1)) if pressure_match else 0

    # 提取位置坐标：如"20.3°N、118.8°E"
    lat_match = re.search(r'([\d.]+)°?\s*[NS北南]', combined)
    lon_match = re.search(r'([\d.]+)°?\s*[EW东西]', combined)
    lat = float(lat_match.group(1)) if lat_match else 0
    lon = float(lon_match.group(1)) if lon_match else 0

    # 提取移动方向：如"西偏北"、"西北方向"
    move_dir_match = re.search(r'(?:向|移向|方向[为是])([东西南北偏]+(?:方向)?)', combined)
    move_dir = move_dir_match.group(1) if move_dir_match else ''

    # 提取移动速度：如"20km/h"、"每小时20公里"
    move_speed_match = re.search(r'(\d+(?:-\d+)?)\s*(?:km/h|公里[/每]小时|千米[/每]小时)', combined)
    move_speed = move_speed_match.group(0) if move_speed_match else ''

    # 提取登陆区域
    landing_match = re.search(r'(?:将在|可能于|预计在|将于)([^，。,.]+(?:一带|沿海|地区|附近|一带沿海))', combined)
    landing_area = landing_match.group(1) if landing_match else ''

    # 提取登陆时间
    landing_time_match = re.search(r'(今夜|今晨|今日|明天|明日|后天|\d+日?凌晨|\d+日?白天|\d+日?夜间|\d+日?\d+[时点])[至到]\d+日?(?:凌晨|白天|夜间|早晨)?', combined)
    if not landing_time_match:
        landing_time_match = re.search(r'(?:登陆时间[：:]?|预计登陆[：:]?)([^，。,.]+)', combined)
    landing_time = landing_time_match.group(0) if landing_time_match else ''

    # 提取登陆强度：如"12-14级"
    landing_strength_match = re.search(r'登陆[^\d]*(\d+(?:-\d+)?)级', combined)
    landing_strength = f"{landing_strength_match.group(1)}级" if landing_strength_match else ''

    # 从预警文本中提取关键影响描述作为 warnings 列表
    warnings_list = []
    # 尝试按句号/分号分割文本，筛选包含降水/风力/影响的句子
    sentences = re.split(r'[。；\n]', text)
    for s in sentences:
        s = s.strip()
        if s and (re.search(r'\d+mm|\d+毫米|暴雨|大暴雨|特大暴雨|降水|雨量', s) or
                  re.search(r'\d+级|阵风|风力|大风', s)):
            if len(s) > 10:  # 过滤过短的片段
                warnings_list.append(s)

    # 如果没有提取到具体描述，用标题和文本的首句
    if not warnings_list and text:
        first_sentence = text.split('。')[0].strip()
        if first_sentence:
            warnings_list.append(first_sentence)

    typhoon_info = {
        "active": True,
        "name": typhoon_name,
        "stormId": storm_id,
        "strength": strength,
        "level": level_str,
        "speed": speed,
        "pressure": pressure,
        "lat": lat,
        "lon": lon,
        "moveDir": move_dir,
        "moveSpeed": move_speed,
        "landingArea": landing_area,
        "landingTime": landing_time,
        "landingStrength": landing_strength,
        "updateTime": latest.get('pubTime', datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')),
        "warnings": warnings_list[:5]  # 最多5条关键影响描述
    }

    print(f"  ✓ 台风信息提取: {typhoon_name or '未识别名称'} ({storm_id}), {strength}, {speed}")
    return typhoon_info


# ============================================================
# GitHub 推送
# ============================================================

def push_to_github(content_str):
    """Push JSON content to GitHub repo"""
    encoded = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
    url = f'https://api.github.com/repos/{OWNER}/{REPO}/contents/{DATA_PATH}'
    headers = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github.v3+json'}

    # GET 获取 sha
    resp = requests.get(url, headers=headers)
    sha = resp.json()['sha'] if resp.status_code == 200 else None

    # PUT 更新
    data = {
        'message': f'chore: update weather data v2 ({datetime.now().strftime("%H:%M")})',
        'content': encoded,
        'branch': 'main'
    }
    if sha:
        data['sha'] = sha

    resp = requests.put(url, headers=headers, json=data)
    if resp.status_code in (200, 201):
        return True
    else:
        print(f"  [ERROR] GitHub推送失败: {resp.status_code} {resp.text[:200]}")
        return False


# ============================================================
# 清理内部字段
# ============================================================

def clean_forecast(forecast_dict):
    """移除预报中的内部字段（_前缀），生成最终输出"""
    cleaned = {}
    for qid, fc_list in forecast_dict.items():
        cleaned[qid] = [
            {k: v for k, v in fc.items() if not k.startswith('_')}
            for fc in fc_list
        ]
    return cleaned


# ============================================================
# 主流程
# ============================================================

def main():
    start_time = time.time()
    print(f"{'='*60}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 天气看板 v2 数据更新开始")
    print(f"城市总数: {len(CITIES)}")
    print(f"{'='*60}")

    # 1. Open-Meteo 批量获取天气+预报
    print("\n[1/3] Open-Meteo 获取天气+预报...")
    weather, forecast = fetch_all_weather_open_meteo()
    print(f"  ✓ 天气: {len(weather)}/{len(CITIES)} 城")
    print(f"  ✓ 预报: {len(forecast)}/{len(CITIES)} 城")

    if not weather:
        print("[ERROR] Open-Meteo获取失败，终止更新")
        sys.exit(1)

    # 2. 预警数据
    print("\n[2/3] 获取预警数据...")
    use_qweather = should_use_qweather_warnings()

    if use_qweather:
        print("  使用和风天气预警API...")
        warnings, warning_calls = fetch_qweather_warnings()
        log_api_usage(warning_calls, 'v2预警数据获取')
        print(f"  ✓ 和风天气预警: {len(warnings)} 城有预警 ({warning_calls}次API调用)")
    else:
        print("  使用Open-Meteo衍生预警...")
        warnings = derive_warnings_from_open_meteo(forecast)
        warning_calls = 0
        print(f"  ✓ 衍生预警: {len(warnings)} 城有预警")

    # 3. 构建并推送
    print("\n[3/3] 构建数据并推送到GitHub...")

    # 清理内部字段
    forecast_output = clean_forecast(forecast)

    # 提取台风信息（从已有预警数据中，不额外消耗API配额）
    print("  提取台风信息...")
    typhoon = extract_typhoon_info(warnings)

    shared = {
        'updateTime': datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        'weather': weather,
        'warning': warnings,
        'forecast': forecast_output,
        'typhoon': typhoon
    }

    json_str = json.dumps(shared, ensure_ascii=False, indent=None)
    print(f"  JSON大小: {len(json_str):,} bytes")

    if push_to_github(json_str):
        print("  ✓ GitHub推送成功！")
    else:
        print("  ✗ GitHub推送失败！")
        sys.exit(1)

    # 4. 汇总
    elapsed = time.time() - start_time
    monthly_used = get_monthly_usage()
    print(f"\n{'='*60}")
    print(f"更新完成！耗时: {elapsed:.1f}秒")
    print(f"  天气数据: {len(weather)} 城")
    print(f"  预报数据: {len(forecast)} 城")
    print(f"  预警数据: {len(warnings)} 城 ({'和风天气' if use_qweather else 'Open-Meteo衍生'})")
    print(f"  台风状态: {'活跃 - ' + typhoon.get('name', '') + ' ' + typhoon.get('strength', '') if typhoon.get('active') else '无活跃台风'}")
    print(f"  和风天气API调用: {warning_calls}次")
    print(f"  本月和风天气累计: {monthly_used}/{MONTHLY_QUOTA} ({monthly_used/MONTHLY_QUOTA*100:.1f}%)")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
