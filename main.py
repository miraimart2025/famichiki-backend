from fastapi import FastAPI
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException, Query
from starlette.status import HTTP_401_UNAUTHORIZED
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta, timezone
import pandas as pd
import xgboost as xgb
import requests
import pytz
import os
from dotenv import load_dotenv
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pydantic import BaseModel
import numpy as np
import math
import random

from users_manager.users_manager import UsersManager
from services.auth_service import AuthService

load_dotenv()

# =========================
# Auth
# =========================
users_manager = UsersManager()
secret_key = os.getenv("SECRET_KEY")
auth_service = AuthService(users_manager, secret_key)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://storage.googleapis.com",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


bearer_scheme = HTTPBearer(auto_error=True)

def get_current_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    token = credentials.credentials
    payload = auth_service.verify_jwt(token)
    if not payload:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload

def get_current_user(payload=Depends(get_current_token)):
    return payload["store_id"]  # "1" or "2" など

class LoginRequest(BaseModel):
    store_id: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@app.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest):
    token = auth_service.authenticate(request.store_id, request.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid store_id or password")
    return TokenResponse(access_token=token)

@app.get("/auth/verify")
def verify_token(current_user=Depends(get_current_user)):
    return {"store_id": current_user, "message": "Token is valid"}

# =========================
# Spreadsheet logging
# =========================
def log_to_spreadsheet(store_id: str, button_name: str, timestamp: str):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    json_str = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not json_str:
        raise RuntimeError("環境変数 GOOGLE_SERVICE_ACCOUNT_JSON が設定されていません")
    json_dict = json.loads(json_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json_dict, scope)
    client = gspread.authorize(creds)

    sheet = client.open("famichiki").sheet1
    # ★ store_id も一緒に記録
    sheet.append_row([timestamp, store_id, button_name])

class ButtonClick(BaseModel):
    button_name: str

JST = pytz.timezone("Asia/Tokyo")

@app.post("/log_button_click")
async def log_button_click(data: ButtonClick, current_user=Depends(get_current_user)):
    timestamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    store_id = str(current_user)  # JWTから取り出したログインID（store_id）
    log_to_spreadsheet(store_id, data.button_name, timestamp)
    return {
        "status": "success",
        "store_id": store_id,
        "message": f"{data.button_name} logged by {store_id} at {timestamp}",
    }

# =========================
# Holiday (fallback)
# =========================
try:
    import jpholiday
    def is_holiday_jp(d):  # d: datetime.date
        return int(jpholiday.is_holiday(d))
except Exception:
    def is_holiday_jp(d):
        return 0

# =========================
# Models
# =========================
MODEL_PATHS = {
    "hondori": {
        "type": "single",
        "model": "./models/model_hondori.json",
        "features": "./models/features_hondori.json",
        "cap": 10,
    },
    "mihara5chome": {
        "type": "two_stage",
        "clf": "./models/model_mihara5chome_clf_cap10.json",
        "reg": "./models/model_mihara5chome_reg_cap10.json",
        "features": "./models/features_mihara5chome_cap10.json",
        "cap": "./models/cap_mihara5chome.json",  # {"CAP": 10}
    },
}

STORE_MAP = {
    "1": "hondori",
    "hondori": "hondori",
    "2": "mihara5chome",
    "mihara5chome": "mihara5chome",
}

MODELS = {}    # store -> dict
FEATURES = {}  # store -> feature_order
CAPS = {}      # store -> int cap

# ★ 深夜（0〜5時）を強制0にするルール（miharaのみ適用）
QUIET_HOURS = set(range(0, 6))  # 0,1,2,3,4,5
QUIET_RULE_STORES = {"mihara5chome"}  # 両店舗にしたいなら {"hondori","mihara5chome"}

def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_store_model(store_name: str):
    conf = MODEL_PATHS[store_name]
    stype = conf["type"]

    # features
    feat_path = conf["features"]
    if not os.path.exists(feat_path):
        raise FileNotFoundError(f"features not found: {feat_path}")
    feature_order = _load_json(feat_path)
    FEATURES[store_name] = feature_order

    # cap
    if stype == "single":
        cap = conf.get("cap", 10)
        CAPS[store_name] = int(cap) if cap is not None else 10
    else:
        cap_path = conf.get("cap")
        if isinstance(cap_path, str) and os.path.exists(cap_path):
            cap_obj = _load_json(cap_path)
            CAPS[store_name] = int(cap_obj.get("CAP", 10))
        else:
            CAPS[store_name] = 10

    # models
    if stype == "single":
        model_path = conf["model"]
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"model not found: {model_path}")
        booster = xgb.Booster()
        booster.load_model(model_path)
        MODELS[store_name] = {"type": "single", "booster": booster}
        print(f"[loaded] {store_name} single model={model_path} features={len(feature_order)} cap={CAPS[store_name]}")

    elif stype == "two_stage":
        clf_path = conf["clf"]
        reg_path = conf["reg"]
        if not os.path.exists(clf_path):
            raise FileNotFoundError(f"clf model not found: {clf_path}")
        if not os.path.exists(reg_path):
            raise FileNotFoundError(f"reg model not found: {reg_path}")

        clf = xgb.Booster()
        clf.load_model(clf_path)
        reg = xgb.Booster()
        reg.load_model(reg_path)

        MODELS[store_name] = {"type": "two_stage", "clf": clf, "reg": reg}
        print(f"[loaded] {store_name} two_stage clf={clf_path} reg={reg_path} features={len(feature_order)} cap={CAPS[store_name]}")
    else:
        raise ValueError(f"unknown model type: {stype}")

# 起動時ロード
for store_name in MODEL_PATHS:
    load_store_model(store_name)

# =========================
# OpenWeather: One Call 3.0 hourly（函館）
# =========================
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
    if res.status_code != 200:
        raise RuntimeError(f"OpenWeather error: {res.status_code} {data}")

    hourly = data.get("hourly", [])
    mapping = {}

    for h in hourly[:hours]:
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
# Feature engineering（学習時と同じ）
# =========================
def apparent_temperature(T_c, RH_pct, ws_ms):
    if any(map(lambda x: x is None or (isinstance(x, float) and np.isnan(x)), [T_c, RH_pct, ws_ms])):
        return np.nan
    es = 6.105 * math.exp(17.27 * T_c / (237.7 + T_c))
    e  = es * RH_pct / 100.0
    return T_c + 0.33 * e - 0.70 * ws_ms - 4.00

def make_feature_row(dt_jst: datetime, w: dict):
    year = dt_jst.year
    month = dt_jst.month
    day = dt_jst.day
    dayofweek = dt_jst.weekday()
    hour = dt_jst.hour
    dayofyear = int(dt_jst.strftime("%j"))
    weekofyear = int(dt_jst.isocalendar().week)

    is_weekend = 1 if dayofweek >= 5 else 0
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
        "year": year, "month": month, "day": day, "dayofweek": dayofweek,
        "hour": hour, "dayofyear": dayofyear, "weekofyear": weekofyear,
        "is_weekend": is_weekend, "is_month_start": is_month_start, "is_month_end": is_month_end,
        "hour_sin": hour_sin, "hour_cos": hour_cos, "dow_sin": dow_sin, "dow_cos": dow_cos,
        "is_holiday": is_holiday,
        "is_payday_25": is_payday_25,
        "is_payweek_before_25": is_payweek_before_25,
        "is_payweek_after_25": is_payweek_after_25,
        "days_to_payday_25": days_to_payday_25,
        "temperature": temperature, "rain": rain, "snow": snow, "wind": wind, "humidity": humidity,
        "is_rain": is_rain, "is_snow": is_snow, "is_high_humidity": is_high_humidity,
        "is_strong_wind": is_strong_wind, "is_comfort_temp": is_comfort_temp,
        "apparent_temperature": app_temp,
    }

# =========================
# Prediction core
# =========================
def _safe_round_clip_to_int(x: float, cap: int) -> int:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 0
    x = float(np.clip(x, 0, cap))
    return int(round(x))

def _predict_single(booster: xgb.Booster, dfX: pd.DataFrame, feature_order: list):
    dmat = xgb.DMatrix(dfX, feature_names=feature_order)
    return booster.predict(dmat)

def _predict_two_stage(clf: xgb.Booster, reg: xgb.Booster, dfX: pd.DataFrame, feature_order: list):
    dmat = xgb.DMatrix(dfX, feature_names=feature_order)
    p_nonzero = clf.predict(dmat)  # probability
    pred_log = reg.predict(dmat)   # log1p scale
    pred_pos = np.expm1(pred_log)
    y_pred = p_nonzero * pred_pos
    return y_pred, p_nonzero

def _predict_random_range(base_dt_jst: datetime, hours: int = 8, low: int = 2, high: int = 5):
    results = []
    for i in range(hours):
        dt = (base_dt_jst + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
        results.append({
            "datetime": dt.strftime("%Y-%m-%d %H:%M"),
            "predicted_sales": random.randint(low, high),
        })
    return results

def predict(store_id: str, base_dt_jst: datetime):
    if str(store_id) == "0000":
        return _predict_random_range(base_dt_jst)

    store_name = STORE_MAP.get(str(store_id))
    if store_name is None:
        raise ValueError("unknown store_id")

    model_pack = MODELS[store_name]
    feature_order = FEATURES[store_name]
    cap = CAPS.get(store_name, 10)

    # 予報は1回だけ取得
    forecast_map = get_hourly_forecast_hakodate(hours=48)

    results = []

    # 0〜5時強制0を適用するか
    apply_quiet_rule = (store_name in QUIET_RULE_STORES)

    rows, dts = [], []
    for i in range(8):
        dt = (base_dt_jst + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)

        # ★ 0〜5時は必ず0（miharaだけ適用）
        if apply_quiet_rule and (dt.hour in QUIET_HOURS):
            results.append({
                "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                "predicted_sales": 0,
            })
            continue

        w = forecast_map.get(dt, {"temperature": np.nan, "humidity": np.nan, "wind": np.nan, "rain": 0.0, "snow": 0.0})
        rows.append(make_feature_row(dt, w))
        dts.append(dt)

    # 全部が深夜でrows空の場合
    if len(rows) == 0:
        return results

    dfX = pd.DataFrame(rows)

    # features揃える（無い列は0）
    for c in feature_order:
        if c not in dfX.columns:
            dfX[c] = 0
    dfX = dfX[feature_order]

    if model_pack["type"] == "single":
        preds = _predict_single(model_pack["booster"], dfX, feature_order)
    else:
        preds, _ = _predict_two_stage(model_pack["clf"], model_pack["reg"], dfX, feature_order)

    # rowsに対応する予測を、resultsへ突っ込む（深夜分はすでに埋め済み）
    pred_iter = iter(preds)
    for i in range(8):
        dt = (base_dt_jst + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)

        if apply_quiet_rule and (dt.hour in QUIET_HOURS):
            # すでに0を入れてる
            continue

        p = float(next(pred_iter))
        results.append({
            "datetime": dt.strftime("%Y-%m-%d %H:%M"),
            "predicted_sales": _safe_round_clip_to_int(p, cap),  # 0〜CAPの整数
        })

    # 8件を時刻順に揃える（深夜continueで順序が崩れるのを防ぐ）
    results = sorted(results, key=lambda x: x["datetime"])
    return results

# =========================
# API endpoints
# =========================
@app.get("/predict")
def predict_sales_batch(current_user=Depends(get_current_user)):
    now = datetime.now(JST).replace(minute=0, second=0, microsecond=0)
    store_id = current_user
    preds = predict(store_id, now)
    return {"predictions": preds}

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
