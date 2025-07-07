from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import pandas as pd
import xgboost as xgb
import requests
import jpholiday
import pytz
import os
from dotenv import load_dotenv
import json

from fastapi import Request
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()
app = FastAPI()

def log_to_spreadsheet(button_name: str, timestamp: str):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_str = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
    json_dict = json.loads(json_str)  # 文字列→辞書に変換
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open("famichiki").sheet1
    sheet.append_row([timestamp, button_name])
from pydantic import BaseModel

from pydantic import BaseModel

class ButtonClick(BaseModel):
    button_name: str

@app.post("/log_button_click")
async def log_button_click(data: ButtonClick):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_to_spreadsheet(data.button_name, timestamp)
    return {"status": "success", "message": f"{data.button_name} logged at {timestamp}"}

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
        
    
# XGBoost Boosterモデルの読み込み
booster = xgb.Booster()
booster.load_model("model.json")  # パスは環境に合わせて調整
        
# 天気情報を取得（函館）
def get_weather_hakodate():
    API_KEY = os.getenv("OPENWEATHER_API_KEY")
    if not API_KEY:
        raise RuntimeError("環境変数 OPENWEATHER_API_KEY が設定されていません")
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": "Hakodate,jp",
        "appid": API_KEY,
        "units": "metric"
    }
    response = requests.get(url, params=params)
    data = response.json()

    return {
        "temp": data["main"]["temp"] + 273.15,
        "temperature": data["main"]["temp"] + 273.15,
        "feels_like": data["main"]["feels_like"] + 273.15,
        "wind_speed": data["wind"]["speed"],
        "wind_deg": data["wind"]["deg"]
    }
        
@app.get("/predict")
def predict_sales_batch():  
    JST = pytz.timezone("Asia/Tokyo")
    now = datetime.now(JST)
    weather = get_weather_hakodate()
    
    span_times = [
        "span_time_8h~9h",
        "span_time_10h~11h",
        "span_time_12h~13h",
        "span_time_14h~15h",
        "span_time_16h~17h",
        "span_time_18h~19h"
    ]
    feature_order = [
        "is_weekend", "day_of_month", "day_of_week", "hour",
        "temp", "wind_speed",
        "span_time_10h~11h", "span_time_12h~13h", "span_time_14h~15h",
        "span_time_16h~17h", "span_time_18h~19h", "span_time_8h~9h",
        "is_holiday", "is_salary_day", "month"
    ]
        
    results = []
        
    for i in range(8):  # 今から8時間分
        dt = now + timedelta(hours=i)  
        hour = dt.hour
    
        # span_time を生成（該当時間だけ1）
        span_time_values = {key: 0 for key in span_times}
        for span in span_times:
            start_hour = int(span.split("_")[2].split("h")[0])
            if hour == start_hour:  
                span_time_values[span] = 1
    
        is_holiday = int(jpholiday.is_holiday(dt))
        
        input_dict = {
            "is_weekend": 1 if dt.weekday() >= 5 else 0,
            "day_of_month": dt.day,
            "day_of_week": dt.weekday(),
            "hour": hour,
            "temp": weather["temp"],
            "wind_speed": weather["wind_speed"],
            "is_holiday": is_holiday,
            "is_salary_day": int(dt.day in [10, 25]),
            "month": dt.month,
            **span_time_values
        }

        df = pd.DataFrame([input_dict])[feature_order]
        dmatrix = xgb.DMatrix(df)
        prediction = booster.predict(dmatrix)[0]
    
        results.append({
            "hour": dt.strftime("%H"),
            "predicted_sales": round(float(prediction))  # 小数点以下を四捨五入して整数に
        })
        
    return {"predictions": results}
from fastapi import Query
from typing import Optional

@app.get("/predict_at")
def predict_sales_at(
    date: str = Query(..., description="日付 (YYYY-MM-DD)"),
    hour: int = Query(..., ge=0, le=23, description="開始時刻 (0〜23時)")
):
    try:
        naive_dt = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour)
        JST = pytz.timezone("Asia/Tokyo")
        base_dt = JST.localize(naive_dt)
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}
            
    weather = get_weather_hakodate()
    
    span_times = [
        "span_time_8h~9h",
        "span_time_10h~11h",
        "span_time_12h~13h",
        "span_time_14h~15h",
        "span_time_16h~17h",
        "span_time_18h~19h"
    ]
            
    feature_order = [
        "is_weekend", "day_of_month", "day_of_week", "hour",
        "temp", "wind_speed", 
        "span_time_10h~11h", "span_time_12h~13h", "span_time_14h~15h",
        "span_time_16h~17h", "span_time_18h~19h", "span_time_8h~9h",
        "is_holiday", "is_salary_day", "month"
    ]

    results = []
    
    for i in range(8):  # 指定時刻から8時間分
        dt = base_dt + timedelta(hours=i)
        hour = dt.hour
        
        # span_time の判定
        span_time_values = {key: 0 for key in span_times}
        for span in span_times:
            start_hour = int(span.split("_")[2].split("h")[0])
            if hour == start_hour:  
                span_time_values[span] = 1
    
        is_holiday = int(jpholiday.is_holiday(dt))
        
        input_dict = {
            "is_weekend": 1 if dt.weekday() >= 5 else 0,
            "day_of_month": dt.day,
            "day_of_week": dt.weekday(),
            "hour": hour,
            "temp": weather["temp"],
            "wind_speed": weather["wind_speed"],
            "is_holiday": is_holiday,
            "is_salary_day": int(dt.day in [10, 25]),
            "month": dt.month,
            **span_time_values
        }

        df = pd.DataFrame([input_dict])[feature_order]
        dmatrix = xgb.DMatrix(df)
        prediction = booster.predict(dmatrix)[0]
    
        results.append({
            "datetime": dt.strftime("%Y-%m-%d %H:%M"),
            "predicted_sales": round(float(prediction), 2)
        })
        
    return {"predictions": results}
            
