"""
Регистрация "виртуального устройства" Rust+ и обмен со Steam-логином.

Публичные константы ниже принадлежат официальному приложению Facepunch Rust+
(Android package com.facepunch.rust.companion) и используются во всех
community-инструментах (rustplus.js, RustPlusApi, RustCli) для регистрации
устройства в Google FCM. Мы не эмулируем Steam-логин — это делает сам
пользователь через официальную страницу Facepunch.
"""

import uuid

import requests
from push_receiver.android_fcm_register import AndroidFCM

API_KEY = "AIzaSyB5y2y-Tzqb4-I4Qnlsh_9naYv_TD8pCvY"
PROJECT_ID = "rust-companion-app"
GCM_SENDER_ID = "976529667804"
GMS_APP_ID = "1:976529667804:android:d6f1ddeb4403b338fea619"
ANDROID_PACKAGE_NAME = "com.facepunch.rust.companion"
ANDROID_PACKAGE_CERT = "E28D05345FB78A7A1A63D70F4A302DBF426CA5AD"

EXPO_PUSH_TOKEN_URL = "https://exp.host/--/api/v2/push/getExpoPushToken"
COMPANION_LOGIN_URL = "https://companion-rust.facepunch.com/login"
COMPANION_REGISTER_URL = "https://companion-rust.facepunch.com/api/push/register"


def register_device():
    """
    Шаг 1: регистрируем устройство в Google FCM. Чистый API-запрос,
    браузер и Steam тут не участвуют.
    Возвращает dict с android_id, security_token, fcm_token.
    """
    result = AndroidFCM.register(
        API_KEY, PROJECT_ID, GCM_SENDER_ID, GMS_APP_ID,
        ANDROID_PACKAGE_NAME, ANDROID_PACKAGE_CERT,
    )
    return {
        "android_id": result["gcm"]["androidId"],
        "security_token": result["gcm"]["securityToken"],
        "fcm_token": result["fcm"]["token"],
    }


def fetch_expo_push_token(fcm_token: str) -> str:
    """Шаг 2: превращаем сырой FCM-токен в ExponentPushToken[...]."""
    device_id = str(uuid.uuid4()).lower()
    resp = requests.post(
        EXPO_PUSH_TOKEN_URL,
        json={
            "type": "fcm",
            "deviceId": device_id,
            "deviceToken": fcm_token,
            "development": False,
            "appId": ANDROID_PACKAGE_NAME,
        },
        timeout=15,
    )
    if not resp.ok:
        # Показываем точный текст ответа, а не просто код ошибки —
        # так сразу видно, какое поле сервер считает неверным.
        raise RuntimeError(f"Expo push token request failed ({resp.status_code}): {resp.text}")
    return resp.json()["data"]["expoPushToken"]


def build_login_url(return_url: str) -> str:
    """Шаг 3: ссылка, по которой пользователь сам логинится через Steam."""
    return f"{COMPANION_LOGIN_URL}?returnUrl={return_url}"


def register_with_companion(steam_token: str, expo_push_token: str) -> str:
    """
    Шаг 5: после того как пришёл steam_token с колбэка, регистрируем
    связку в Rust Companion API. Возвращает обновлённый (2-недельный) токен.

    ВАЖНО: это единственный шаг, который стоит проверить вживую —
    точный формат тела запроса нигде официально не задокументирован,
    он восстановлен по поведению клиентов сообщества. Если Facepunch
    вернёт ошибку, смотри тело ответа (resp.text) и подгоняй ключи.
    """
    resp = requests.post(
        COMPANION_REGISTER_URL,
        headers={"Authorization": f"Bearer {steam_token}"},
        json={"AuthToken": steam_token, "DeviceId": "rustplus-tg-bot", "PushKind": 0, "PushToken": expo_push_token},
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f"Companion register failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    return data.get("token", steam_token)
