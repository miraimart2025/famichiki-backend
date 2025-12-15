from fastapi import FastAPI, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta, timezone
import pandas as pd
import xgboost as xgb
import requests
import jpholiday
import pytz
import os
from dotenv import load_dotenv
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pydantic import BaseModel
import numpy as np
import math
from users_manager.users_manager import UsersManager
from services.auth_service import AuthService

load_dotenv()

# AuthServiceを初期化
users_manager = UsersManager()
secret_key = os.getenv("SECRET_KEY")
auth_service = AuthService(users_manager, secret_key)

# FastAPIアプリケーションの初期化
app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JWT関連設定
bearer_scheme = HTTPBearer(auto_error=True)

def get_current_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    token = credentials.credentials
    payload = auth_service.verify_jwt(token)
    if not payload:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload

def get_current_user(payload=Depends(get_current_token)):
    return payload["store_id"]

# リクエストボディ用スキーマ
class LoginRequest(BaseModel):
    store_id: str
    password: str

# レスポンス用スキーマ
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@app.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest):
    """
    認証API：
    store_idとpasswordを受け取り、認証成功時にJWTを返す。
    """
    token = auth_service.authenticate(request.store_id, request.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid store_id or password")
    
    return TokenResponse(access_token=token)

@app.get("/auth/verify")
def verify_token(current_user=Depends(get_current_user)):
    return {"store_id": current_user, "message": "Token is valid"}

def log_to_spreadsheet(button_name: str, timestamp: str):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_str = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
    json_dict = json.loads(json_str)  # 文字列→辞書に変換
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open("famichiki").sheet1
    sheet.append_row([timestamp, button_name])


class ButtonClick(BaseModel):
    button_name: str

@app.post("/log_button_click")
async def log_button_click(
    data: ButtonClick,
    current_user=Depends(get_current_user)
):
    JST = pytz.timezone("Asia/Tokyo")
    timestamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    store_id = current_user
    log_to_spreadsheet(data.button_name, timestamp)
    return {"status": "success", "message": f"{data.button_name} logged at {timestamp}"}

        
    
# 祝日判定
try:
    import jpholiday
    def is_holiday_jp(d):  # d: datetime.date
        return int(jpholiday.is_holiday(d))
except Exception:
    # requirementsに入れるのが正解。暫定で0返し
    def is_holiday_jp(d):
        return 0

JST = pytz.timezone("Asia/Tokyo")

# ★ここを直指定（例：backend直下に models/ を置く想定）
MODEL_PATHS = {
    "hondori": {
        "model": "./models/model_hondori.json",
        "features": "./models/features_hondori.json",
    },
    "mihara5chome": {
        "model": "./models/model_mihara5chome.json",
        "features": "./models/features_mihara5chome.json",
    },
}

STORE_MAP = {
    # 数値IDと店舗名どちらでも指定できるようにしておく
    "1": "hondori",
    "hondori": "hondori",
    "2": "mihara5chome",
    "mihara5chome": "mihara5chome",
}

MODELS = {}
FEATURES = {}

def load_store_model(store_name: str):
    model_path = MODEL_PATHS[store_name]["model"]
    feat_path  = MODEL_PATHS[store_name]["features"]

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"model not found: {model_path}")
    if not os.path.exists(feat_path):
        raise FileNotFoundError(f"features not found: {feat_path}")

    booster = xgb.Booster()
    booster.load_model(model_path)

    with open(feat_path, "r", encoding="utf-8") as f:
        feature_order = json.load(f)

    MODELS[store_name] = booster
    FEATURES[store_name] = feature_order
    print(f"[loaded] {store_name} model={model_path} features={len(feature_order)}")

# 起動時にロード（MODEL_PATHS に追加するだけで自動で読み込む）
for store_name in MODEL_PATHS:
    load_store_model(store_name)

# =========================
# OpenWeather: One Call 3.0 hourly（函館）
# =========================
# One Call 3.0: https://api.openweathermap.org/data/3.0/onecall?lat=...&lon=...&exclude=...&appid=...
# hourly予報は最大48時間 :contentReference[oaicite:2]{index=2}

HAKODATE_LAT = 41.77583
HAKODATE_LON = 140.73667

def get_hourly_forecast_hakodate(hours: int = 48):
    API_KEY = os.getenv("OPENWEATHER_API_KEY")
    if not API_KEY:
        raise RuntimeError("環境変数 OPENWEATHER_API_KEY が設定されていません")

    url = "https://api.openweathermap.org/data/3.0/onecall"
    params = {
        "lat": HAKODATE_LAT,
        "lon": HAKODATE_LON,
        "appid": API_KEY,
        "units": "metric",
        "exclude": "minutely,daily,alerts"
    }
    res = requests.get(url, params=params, timeout=10)
    data = res.json()

    # エラー時に分かるように
    if res.status_code != 200:
        raise RuntimeError(f"OpenWeather error: {res.status_code} {data}")

    hourly = data.get("hourly", [])
    mapping = {}

    for h in hourly[:hours]:
        # ★UTC→JSTに変換して、JSTの「ちょうどの時刻」をキーにする
        dt_jst = datetime.fromtimestamp(int(h["dt"]), tz=timezone.utc).astimezone(JST)
        dt_key = dt_jst.replace(minute=0, second=0, microsecond=0)

        rain_1h = 0.0
        if isinstance(h.get("rain"), dict):
            rain_1h = float(h["rain"].get("1h", 0.0))

        snow_1h = 0.0
        if isinstance(h.get("snow"), dict):
            snow_1h = float(h["snow"].get("1h", 0.0))

        mapping[dt_key] = {
            "temperature": float(h.get("temp", np.nan)),
            "humidity": float(h.get("humidity", np.nan)),
            "wind": float(h.get("wind_speed", np.nan)),
            "rain": rain_1h,
            "snow": snow_1h,
        }

    return mapping

# =========================
# 特徴量生成（学習時と同じ定義に寄せる）
# =========================
def apparent_temperature(T_c, RH_pct, ws_ms):
    # 学習時と同じ（Tetens→e→Steadman近似）
    if any(map(lambda x: x is None or (isinstance(x, float) and np.isnan(x)), [T_c, RH_pct, ws_ms])):
        return np.nan
    es = 6.105 * math.exp(17.27 * T_c / (237.7 + T_c))
    e  = es * RH_pct / 100.0
    return T_c + 0.33 * e - 0.70 * ws_ms - 4.00

def make_feature_row(dt_jst: datetime, w: dict):
    # time/calendar
    year = dt_jst.year
    month = dt_jst.month
    day = dt_jst.day
    dayofweek = dt_jst.weekday()        # Mon=0
    hour = dt_jst.hour
    dayofyear = int(dt_jst.strftime("%j"))
    weekofyear = int(dt_jst.isocalendar().week)

    is_weekend = 1 if dayofweek >= 5 else 0
    # 月末判定（翌日が1日）
    is_month_end = 1 if (dt_jst + timedelta(days=1)).day == 1 else 0
    is_month_start = 1 if day == 1 else 0

    hour_sin = math.sin(2 * math.pi * hour / 24.0)
    hour_cos = math.cos(2 * math.pi * hour / 24.0)
    dow_sin  = math.sin(2 * math.pi * dayofweek / 7.0)
    dow_cos  = math.cos(2 * math.pi * dayofweek / 7.0)

    is_holiday = is_holiday_jp(dt_jst.date())

    pay_day = 25
    is_payday_25 = 1 if day == pay_day else 0
    is_payweek_before_25 = 1 if (pay_day - 5) <= day <= (pay_day - 1) else 0
    is_payweek_after_25  = 1 if (pay_day + 1) <= day <= (pay_day + 3) else 0
    days_to_payday_25 = pay_day - day

    # weather
    temperature = float(w.get("temperature", np.nan))
    rain = float(w.get("rain", 0.0))
    snow = float(w.get("snow", 0.0))
    wind = float(w.get("wind", np.nan))
    humidity = float(w.get("humidity", np.nan))

    is_rain = 1 if rain > 0 else 0
    is_snow = 1 if snow > 0 else 0
    is_high_humidity = 1 if (not np.isnan(humidity) and humidity >= 70) else 0
    is_strong_wind = 1 if (not np.isnan(wind) and wind >= 5) else 0
    is_comfort_temp = 1 if (not np.isnan(temperature) and 15 <= temperature <= 25) else 0

    app_temp = apparent_temperature(temperature, humidity, wind)

    return {
        # time
        "year": year, "month": month, "day": day, "dayofweek": dayofweek,
        "hour": hour, "dayofyear": dayofyear, "weekofyear": weekofyear,
        "is_weekend": is_weekend, "is_month_start": is_month_start, "is_month_end": is_month_end,
        "hour_sin": hour_sin, "hour_cos": hour_cos, "dow_sin": dow_sin, "dow_cos": dow_cos,
        "is_holiday": is_holiday,
        # payday
        "is_payday_25": is_payday_25,
        "is_payweek_before_25": is_payweek_before_25,
        "is_payweek_after_25": is_payweek_after_25,
        "days_to_payday_25": days_to_payday_25,
        # weather
        "temperature": temperature, "rain": rain, "snow": snow, "wind": wind, "humidity": humidity,
        "is_rain": is_rain, "is_snow": is_snow, "is_high_humidity": is_high_humidity,
        "is_strong_wind": is_strong_wind, "is_comfort_temp": is_comfort_temp,
        "apparent_temperature": app_temp,
    }

def predict(store_id: str, base_dt_jst: datetime):
    store_name = STORE_MAP.get(store_id)
    if store_name is None:
        raise ValueError("unknown store_id")

    booster = MODELS[store_name]
    feature_order = FEATURES[store_name]

    # 予報取得（直近のhourlyからマッチ）
    forecast_map = get_hourly_forecast_hakodate(hours=48)

    rows = []
    dts = []
    for i in range(8):
        dt = (base_dt_jst + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)

        # 予報が無ければ 0/NaN で埋め（8時間先なら普通はある）
        w = forecast_map.get(dt, {"temperature": np.nan, "humidity": np.nan, "wind": np.nan, "rain": 0.0, "snow": 0.0})

        row = make_feature_row(dt, w)
        rows.append(row)
        dts.append(dt)

    dfX = pd.DataFrame(rows)

    # 学習時に使った特徴量だけ、順序通りにそろえる（無い列は0）
    for c in feature_order:
        if c not in dfX.columns:
            dfX[c] = 0
    dfX = dfX[feature_order]

    dmat = xgb.DMatrix(dfX, feature_names=feature_order)
    preds = booster.predict(dmat)

    results = []
    for dt, p in zip(dts, preds):
        results.append({
            "datetime": dt.strftime("%Y-%m-%d %H:%M"),
            "predicted_sales": int(round(float(p)))
        })
    return results
        
@app.get("/predict")
def predict_sales_batch(current_user=Depends(get_current_user)):
    now = datetime.now(JST).replace(minute=0, second=0, microsecond=0)
    store_id = current_user  # "hondori" や "mihara5chome" など

    preds = predict(store_id, now)
    return {"predictions": preds}


from fastapi import Query

@app.get("/predict_at")
def predict_sales_at(
    date: str = Query(..., description="日付 (YYYY-MM-DD)"),
    hour: int = Query(..., ge=0, le=23, description="開始時刻 (0〜23時)"),
    current_user=Depends(get_current_user)
):
    try:
        naive = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, minute=0, second=0, microsecond=0)
        base_dt = JST.localize(naive)
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    store_id = current_user
    preds = predict(store_id, base_dt)
    return {"predictions": preds}
