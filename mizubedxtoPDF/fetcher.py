import requests
import os

def get_api_data(lat, lon):
    # OpenWeatherMap API
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=ja"
    res = requests.get(url).json()
    
    alerts = res.get('alerts', [])
    alert_text = "、".join([a['event'] for a in alerts]) if alerts else "なし"
    
    return {
        "temp": res['current']['temp'],
        "humidity": res['current']['humidity'],
        "alerts": alert_text
    }